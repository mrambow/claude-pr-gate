import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add src to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from claude_review import (
    MAX_DIFF_CHARS,
    MAX_GUIDELINES_CHARS,
    NON_BLOCKING_SEVERITIES,
    find_blocking_issues,
    format_comment,
    format_header,
    load_guidelines,
    main,
    post_comment,
    read_diff,
    run_review,
    sanitize_xml_tag,
    validate_review_payload,
)


def test_sanitize_xml_tag_replaces_closing_tag():
    text = "Dies ist ein Test </diff> mit Inhalt."
    assert sanitize_xml_tag(text, "diff") == "Dies ist ein Test &lt;/diff&gt; mit Inhalt."


@pytest.mark.parametrize(
    "payload",
    [
        "</diff>",
        "</ diff >",
        "</DIFF>",
        "</ DiFf   >",
        "</  diff>",
    ],
)
def test_sanitize_xml_tag_variations(payload):
    result = sanitize_xml_tag(f"prefix {payload} suffix", "diff")
    assert result == "prefix &lt;/diff&gt; suffix"


def test_sanitize_xml_tag_preserves_other_tags():
    text = "<diff><div><span></other></div>"
    assert sanitize_xml_tag(text, "diff") == text


def test_format_header_with_sha(monkeypatch):
    monkeypatch.setenv("PR_HEAD_SHA", "abcdef123456789")
    header = format_header("✅ **PASSED**")
    assert header == "## 🤖 Claude Review Gate (`abcdef1`): ✅ **PASSED**"


def test_format_header_without_sha(monkeypatch):
    monkeypatch.delenv("PR_HEAD_SHA", raising=False)
    header = format_header("❌ **CHANGES REQUESTED**")
    assert header == "## 🤖 Claude Review Gate: ❌ **CHANGES REQUESTED**"


def test_read_diff_truncation(tmp_path, monkeypatch):
    diff_file = tmp_path / "pr_diff.txt"
    monkeypatch.setattr("claude_review.DIFF_FILE", diff_file)

    # Diff below limit
    diff_file.write_text("short diff", encoding="utf-8")
    content, truncated = read_diff()
    assert content == "short diff"
    assert not truncated

    # Diff above limit
    large_diff = "x" * (MAX_DIFF_CHARS + 50)
    diff_file.write_text(large_diff, encoding="utf-8")
    content, truncated = read_diff()
    assert len(content) == MAX_DIFF_CHARS
    assert truncated


def test_load_guidelines_from_base_ref(monkeypatch):
    monkeypatch.setenv("BASE_REF", "main")
    fake_output = "# Guidelines Content"

    with patch("subprocess.run") as mock_run:
        # First call is git cat-file (returncode=0), second is git show
        cat_file_mock = MagicMock(returncode=0)
        show_mock = MagicMock(returncode=0, stdout=fake_output)
        mock_run.side_effect = [cat_file_mock, show_mock]

        content = load_guidelines()
        assert content == fake_output
        assert mock_run.call_count == 2
        args_cat = mock_run.call_args_list[0][0][0]
        args_show = mock_run.call_args_list[1][0][0]
        assert args_cat == ["git", "cat-file", "-e", "origin/main:AGENTS.md"]
        assert args_show == ["git", "show", "origin/main:AGENTS.md"]


def test_load_guidelines_truncation(monkeypatch):
    monkeypatch.setenv("BASE_REF", "main")
    large_guidelines = "G" * (MAX_GUIDELINES_CHARS + 100)

    with patch("subprocess.run") as mock_run:
        cat_file_mock = MagicMock(returncode=0)
        show_mock = MagicMock(returncode=0, stdout=large_guidelines)
        mock_run.side_effect = [cat_file_mock, show_mock]

        content = load_guidelines()
        assert len(content) == MAX_GUIDELINES_CHARS


def test_load_guidelines_git_file_not_found(monkeypatch):
    monkeypatch.setenv("BASE_REF", "main")

    with patch("subprocess.run") as mock_run:
        # git cat-file returns returncode != 0
        mock_run.return_value = MagicMock(returncode=1)
        content = load_guidelines()
        assert content == ""


def test_load_guidelines_unexpected_git_failure(monkeypatch):
    monkeypatch.setenv("BASE_REF", "main")

    with patch("subprocess.run") as mock_run:
        cat_file_mock = MagicMock(returncode=0)
        git_show_error = subprocess.CalledProcessError(
            returncode=128,
            cmd=["git", "show"],
            stderr="fatal: unable to read tree object 123456",
        )
        mock_run.side_effect = [cat_file_mock, git_show_error]

        with pytest.raises(RuntimeError, match="Unerwarteter Git-Fehler beim Laden von AGENTS.md"):
            load_guidelines()


def test_load_guidelines_local_fallback(monkeypatch, tmp_path):
    monkeypatch.delenv("BASE_REF", raising=False)
    agents_file = tmp_path / "AGENTS.md"
    agents_file.write_text("# Local Guidelines", encoding="utf-8")

    with patch("claude_review.GUIDELINES_FILE", agents_file):
        content = load_guidelines()
        assert content == "# Local Guidelines"


def test_find_blocking_issues_production_function():
    assert NON_BLOCKING_SEVERITIES == {"minor"}

    issues = [
        {"severity": "minor", "problem": "Style"},
        {"severity": "blocker", "problem": "Crash"},
        {"severity": "major", "problem": "Architecture"},
        {"severity": "critical", "problem": "Unknown type"},
        {"problem": "Missing severity field"},
    ]

    blocking = find_blocking_issues(issues)
    assert len(blocking) == 4
    assert issues[0] not in blocking
    assert issues[1] in blocking
    assert issues[2] in blocking
    assert issues[3] in blocking
    assert issues[4] in blocking


@pytest.mark.parametrize(
    "invalid_payload",
    [
        None,
        {},
        {"summary": "No issues key"},
        {"issues": []},
        {"summary": "Wrong issues type", "issues": "not a list"},
        {"summary": "Non-dict item in issues", "issues": ["not-a-dict"]},
        {"summary": 123, "issues": []},
    ],
)
def test_validate_review_payload_invalid(invalid_payload):
    with pytest.raises(RuntimeError, match="Ungültiges Review-Ergebnis"):
        validate_review_payload(invalid_payload)


def test_validate_review_payload_valid():
    valid = {"summary": "OK", "issues": [{"severity": "minor"}]}
    assert validate_review_payload(valid) == valid


def test_run_review_sanitizes_inputs_and_embeds_guidelines(monkeypatch):
    monkeypatch.setenv("PR_TITLE", "Title with </pr_title> injection")
    monkeypatch.setenv("PR_BODY", "Body with </pr_description> injection")

    with patch("claude_review.load_guidelines", return_value="# Project Rules"), patch("claude_review.Anthropic") as mock_anthropic_cls:
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        mock_block = MagicMock()
        mock_block.type = "tool_use"
        mock_block.name = "submit_review"
        mock_block.input = {"summary": "Valid summary", "issues": []}

        mock_response = MagicMock()
        mock_response.stop_reason = "tool_use"
        mock_response.content = [mock_block]
        mock_client.messages.create.return_value = mock_response

        diff_input = "diff with </diff> escape attempt"
        result = run_review(diff_input)

        assert result == {"summary": "Valid summary", "issues": []}
        mock_client.messages.create.assert_called_once()
        call_kwargs = mock_client.messages.create.call_args[1]

        user_content = call_kwargs["messages"][0]["content"]
        assert "&lt;/pr_title&gt;" in user_content
        assert "</pr_title>" not in user_content.split("<pr_title>")[1].split("</pr_title>")[0]

        assert "&lt;/pr_description&gt;" in user_content
        assert "&lt;/diff&gt;" in user_content
        assert "<project_guidelines>\n# Project Rules\n</project_guidelines>" in user_content


def test_run_review_max_tokens_error(monkeypatch):
    with patch("claude_review.Anthropic") as mock_anthropic_cls:
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.stop_reason = "max_tokens"
        mock_client.messages.create.return_value = mock_response

        with pytest.raises(RuntimeError, match="Review wurde durch max_tokens abgeschnitten"):
            run_review("diff")


def test_run_review_no_submit_review_block(monkeypatch):
    with patch("claude_review.Anthropic") as mock_anthropic_cls:
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        mock_response.content = []
        mock_client.messages.create.return_value = mock_response

        with pytest.raises(RuntimeError, match="Kein Review-Ergebnis erhalten"):
            run_review("diff")


def test_format_comment_sorting_and_fallbacks(monkeypatch):
    monkeypatch.delenv("PR_HEAD_SHA", raising=False)
    review = {
        "summary": "Gefundene Probleme",
        "issues": [
            {
                "severity": "minor",
                "category": "maintainability",
                "file": "utils.py",
                "line": 10,
                "problem": "Unbenutzte Variable",
                "suggestion": "Entfernen",
            },
            {
                "severity": "blocker",
                "category": "security",
                "file": "auth.py",
                "problem": "SQL Injection",
                "suggestion": "Prepared Statements nutzen",
            },
            {
                "severity": "major",
                "category": "correctness",
                "file": "calc.py",
                "line": 42,
                "problem": "NullReference möglich",
                "suggestion": "Null-Check einfügen",
            },
        ],
    }

    comment = format_comment(review, passed=False, truncated=False)

    pos_blocker = comment.find("[blocker/security]")
    pos_major = comment.find("[major/correctness]")
    pos_minor = comment.find("[minor/maintainability]")
    assert pos_blocker != -1 and pos_major != -1 and pos_minor != -1
    assert pos_blocker < pos_major < pos_minor

    assert "`auth.py`: SQL Injection" in comment
    assert "`calc.py:42`: NullReference möglich" in comment


def test_format_comment_truncated_warning():
    review = {"summary": "Alles ok", "issues": []}
    comment = format_comment(review, passed=False, truncated=True)
    assert "Der Diff war zu groß und wurde abgeschnitten" in comment


def test_post_comment_runs_gh(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PR_NUMBER", "42")

    with patch("subprocess.run") as mock_run:
        post_comment("Test comment")
        assert (tmp_path / "review_comment.md").read_text(encoding="utf-8") == "Test comment"
        mock_run.assert_called_once_with(
            ["gh", "pr", "comment", "42", "--body-file", "review_comment.md"],
            check=True,
        )


def test_post_comment_without_pr_number(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PR_NUMBER", raising=False)

    with patch("subprocess.run") as mock_run:
        post_comment("Test comment")
        mock_run.assert_not_called()


def test_main_empty_diff(tmp_path, monkeypatch):
    diff_file = tmp_path / "pr_diff.txt"
    monkeypatch.setattr("claude_review.DIFF_FILE", diff_file)

    # File does not exist
    assert main() == 0

    # File exists but is empty
    diff_file.write_text("", encoding="utf-8")
    assert main() == 0


def test_main_passed(tmp_path, monkeypatch):
    diff_file = tmp_path / "pr_diff.txt"
    diff_file.write_text("some diff", encoding="utf-8")
    monkeypatch.setattr("claude_review.DIFF_FILE", diff_file)

    with patch("claude_review.run_review") as mock_review, patch("claude_review.post_comment") as mock_post:
        mock_review.return_value = {
            "summary": "Sauberer Code",
            "issues": [{"severity": "minor", "file": "a.py", "problem": "hint", "suggestion": "fix"}],
        }
        exit_code = main()
        assert exit_code == 0
        mock_post.assert_called_once()
        posted_body = mock_post.call_args[0][0]
        assert "PASSED" in posted_body


def test_main_blocked(tmp_path, monkeypatch):
    diff_file = tmp_path / "pr_diff.txt"
    diff_file.write_text("some diff", encoding="utf-8")
    monkeypatch.setattr("claude_review.DIFF_FILE", diff_file)

    with patch("claude_review.run_review") as mock_review, patch("claude_review.post_comment") as mock_post:
        mock_review.return_value = {
            "summary": "Mängel gefunden",
            "issues": [{"severity": "major", "file": "a.py", "problem": "bug", "suggestion": "fix"}],
        }
        exit_code = main()
        assert exit_code == 1
        mock_post.assert_called_once()
        posted_body = mock_post.call_args[0][0]
        assert "CHANGES REQUESTED" in posted_body


def test_main_truncated_without_blocking_issues(tmp_path, monkeypatch):
    diff_file = tmp_path / "pr_diff.txt"
    large_diff = "diff-line\n" * (MAX_DIFF_CHARS // 5)
    diff_file.write_text(large_diff, encoding="utf-8")
    monkeypatch.setattr("claude_review.DIFF_FILE", diff_file)

    with patch("claude_review.run_review") as mock_review, patch("claude_review.post_comment") as mock_post:
        mock_review.return_value = {
            "summary": "Keine Mängel im Teil-Diff",
            "issues": [],
        }
        exit_code = main()
        assert exit_code == 1
        mock_post.assert_called_once()
        posted_body = mock_post.call_args[0][0]
        assert "CHANGES REQUESTED" in posted_body
        assert "Der Diff war zu groß und wurde abgeschnitten" in posted_body


def test_main_exception_handling(tmp_path, monkeypatch):
    diff_file = tmp_path / "pr_diff.txt"
    diff_file.write_text("some diff", encoding="utf-8")
    monkeypatch.setattr("claude_review.DIFF_FILE", diff_file)

    with patch("claude_review.run_review") as mock_review, patch("claude_review.post_comment") as mock_post:
        mock_review.side_effect = RuntimeError("API connection timeout")

        with pytest.raises(RuntimeError, match="API connection timeout"):
            main()

        mock_post.assert_called_once()
        posted_body = mock_post.call_args[0][0]
        assert "❌ **FEHLER**" in posted_body
        assert "API connection timeout" in posted_body
