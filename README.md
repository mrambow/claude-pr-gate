# Claude PR Review Gate 🤖🛡️

[![CI](https://github.com/mrambow/claude-pr-gate/actions/workflows/ci.yml/badge.svg)](https://github.com/mrambow/claude-pr-gate/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A security-hardened, automated **PR Review Gatekeeper** GitHub Action powered by **Anthropic Claude**. Designed for high-reliability development teams and autonomous agent workflows adhering to the **Maker-Checker Principle**.

---

## ✨ Features

- 🔒 **Fail-Closed Security**: Only explicit `minor` findings pass. Unknown severities, parsing issues or model errors immediately block the PR.
- 🛡️ **Prompt-Injection Defense**: All untrusted inputs (PR Title, Description, Git Diff) are strictly sanitized against XML container escapes (e.g. `</diff>`, `</pr_title>`).
- 🔄 **Incremental Re-Review**: Automatically extracts the last reviewed commit SHA from PR comments via `gh`, verifies git ancestry, and evaluates only the delta (`last_sha..HEAD`) against previous findings. Prevents expensive full re-reviews when fixing reported issues.
- 🎯 **Single-Pass Issue Reporting**: Eliminates artificial findings limits for `blocker` and `major` issues so authors receive all critical feedback in one pass rather than iterative rounds.
- 📂 **Base-Branch Isolation**: Project guidelines (e.g. `AGENTS.md`) are verified and loaded directly from `origin/$BASE_REF` via `git cat-file` and `git show` with locale-independent error handling. A PR cannot weaken its own evaluation rules.
- 🚫 **Anti-Tampering by Design**: Running as an external GitHub Action prevents PR branches from modifying the gatekeeper script or its dependencies.
- 🔍 **Traceability**: Review comments are explicitly tagged with the first 7 characters of the reviewed Commit-SHA (`PR_HEAD_SHA`).
- 🪙 **Token Usage & Job Summary**: Logs input, output (reasoning), and cache token usage to the console and adds a clean markdown table to `$GITHUB_STEP_SUMMARY`.
- 🧭 **Focused Context**: Injects file statistics (`git diff --stat`) and balanced surrounding context lines (`-U5` by default) so Claude catches missing tests and function signatures without burning tokens.
- ⚡ **Highly Configurable**: Custom exclusion patterns for diffs, custom context line depth, custom models, token limits, and guideline file paths.

---

## 🚀 Quickstart

Create a workflow file in your repository, e.g. `.github/workflows/claude-pr-gate.yml`:

```yaml
name: Claude PR Review Gate

on:
  pull_request:
    types: [opened, ready_for_review, labeled]

concurrency:
  group: claude-review-${{ github.event.pull_request.number }}
  cancel-in-progress: true

jobs:
  test:
    name: Build, Lint & Tests
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Code
        uses: actions/checkout@v4

      # Vorschalten schneller, billiger Checks (z. B. npm test, dotnet test, pytest)
      # Ein fehlschlagender Build braucht kein teures Claude-Review!
      - name: Tests ausführen
        run: echo "Run tests and linting here"

  review:
    name: Claude PR Review Gate
    needs: [test] # Läuft erst, wenn alle billigen Standard-Checks grün sind!
    # Überspringt Drafts, Bots und läuft bei Pushs nur nach explizitem Setzen des 'review'-Labels
    if: >-
      github.event.pull_request.draft == false &&
      github.event.pull_request.head.repo.full_name == github.repository &&
      github.event.pull_request.user.login != 'dependabot[bot]' &&
      (github.event.action != 'labeled' || github.event.label.name == 'review')
    runs-on: ubuntu-latest
    timeout-minutes: 15
    permissions:
      contents: read
      pull-requests: write

    steps:
      - name: Checkout Code
        uses: actions/checkout@v4
        with:
          fetch-depth: 0 # Notwendig für Diff-Berechnung und inkrementelles Re-Review

      - name: Claude PR Review Gate
        uses: mrambow/claude-pr-gate@v1 # oder @<commit-sha>
        with:
          anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
          diff-excludes: |
            :!package-lock.json
            :!pnpm-lock.yaml
            :!yarn.lock
            :!*.min.*
            :!**/dist/**
            :!**/bin/**
            :!**/obj/**
```

---

## ⚙️ Inputs

| Input | Description | Required | Default |
| :--- | :--- | :---: | :--- |
| `anthropic-api-key` | Anthropic API Key | **Yes** | — |
| `github-token` | GitHub Token with `pull-requests: write` permission | No | `${{ github.token }}` |
| `base-ref` | Target base branch ref | No | `${{ github.base_ref }}` |
| `diff-excludes` | Patterns to exclude from git diff | No | `':!package-lock.json' ':!pnpm-lock.yaml' ':!yarn.lock' ':!*.min.*' ':!*.snap' ':!*.svg' ':!**/dist/**'` |
| `model` | Claude model name | No | `claude-sonnet-5-5` |
| `effort` | Reasoning effort: `low`, `medium`, `high`, `xhigh`, `max` (invalid values fail the run) | No | `medium` |
| `guidelines-file` | Path to project guidelines (relative to repo root) | No | `AGENTS.md` |
| `max-diff-chars` | Max diff character limit before truncation | No | `400000` |
| `diff-context-lines` | Number of context lines around changes for git diff (-U<n>) | No | `5` |

---

## 💰 Token- & Budget-Optimierung

Große PRs und iterative Fixes können bei LLM-Reviews schnell das Budget belasten. Das Gate bietet integrierte Schutzmechanismen:

1. **Inkrementelles Re-Review (Automatisch aktiviert)**:
   - Sobald das Gate einen PR bereits kommentiert hat, liest der Folge-Lauf den Commit-SHA aus dem vorherigen Kommentar.
   - Wenn der Commit im Git-Verlauf liegt, wird nur das Delta (`last_sha..HEAD`) geprüft.
   - Claude erhält die vorherigen Findings mit dem Auftrag: *"Prüfe, ob die alten Mängel behoben sind und ob im Delta neue Probleme entstanden sind."*
   - Spart typischerweise **70–90% der Input-Tokens** bei Nachbesserungsrunden.

2. **Explizites Review-Label (`review`)**:
   - Automatische Runs bei jedem `git push` (`synchronize`) abschalten.
   - Entwickler oder autonome Coding-Agents (wie Gemini / Claude Code) können unbegrenzt Fix-Commits pushen.
   - Wenn der PR reif ist: Label `review` setzen. Für eine erneute Runde das Label kurz entfernen und wieder setzen.

3. **Billige Checks vorschalten (`needs: [test]`)**:
   - Vor das Claude-Gate immer Standard-CI-Jobs hängen (Build, Linter, Type-Checker, Unit-Tests).
   - Ein Code-Stand, der nicht kompiliert oder dessen Tests rot sind, benötigt kein teures LLM-Review.

4. **Verbrauchskontrolle & Job-Summary**:
   - Das Gate loggt Input-, Output- (inkl. Extended Thinking) und Cache-Tokens in die Konsole und in das GitHub Actions **Job Summary**.
   - Dadurch ist sofort ersichtlich, ob ein einzelner Ausreißer-PR oder viele Läufe für den Token-Verbrauch verantwortlich sind.

5. **Spend-Limits in Anthropic einrichten**:
   - Erstelle in der Anthropic Console einen separaten Workspace oder API-Key für CI/Actions.
   - Hinterlege ein striktes monatliches Budget-Limit (Spend Limit), damit fehlerhafte Endlosschleifen oder Riesen-PRs niemals dein primäres Entwicklungsbudget aufbrauchen.

---

## 🎚️ Per-PR Model & Effort (e.g. via Label)

Inputs accept GitHub expressions, so you can escalate individual PRs to a stronger model. Example: the label `deep-review` switches to Opus:

```yaml
on:
  pull_request:
    # labeled/unlabeled are required so that adding the label re-triggers the review
    types: [opened, synchronize, reopened, ready_for_review, labeled, unlabeled]

# ...
      - name: Claude PR Review Gate
        uses: mrambow/claude-pr-gate@v1
        with:
          anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
          model: ${{ contains(github.event.pull_request.labels.*.name, 'deep-review') && 'claude-opus-5-5' || 'claude-sonnet-5-5' }}
          # effort works the same way, e.g. `... && 'xhigh' || 'high'`
```

> Labels are preferable to keywords in the PR body: only users with triage permissions can set labels, whereas any PR author controls the body.

---

## 🏗️ Review Priority & Criteria

Claude evaluates your pull requests in strict priority order:

1. **Correctness**: Logical bugs, race conditions, edge cases, error handling, null/empty checks, leaks, backwards compatibility.
2. **Security**: Injection vulnerabilities, unvalidated input, secrets, auth checks, insecure defaults.
3. **YAGNI & KISS**: Dead code, speculative abstractions, unused parameters, over-engineering.
4. **SOLID & Architecture**: Separation of concerns, dependency injection, adherence to local `AGENTS.md` architectural conventions.
5. **Maintainability & Tests**: Readability, test coverage for new logic or bugfixes.

Findings are reported via GitHub PR comments:
- ❌ **`blocker`**: Security vulnerability, critical bug, data loss risk (Blocks PR).
- ❌ **`major`**: Serious architectural or maintainability issue (Blocks PR).
- 💡 **`minor`**: Non-blocking improvement or hint.

---

## 🧪 Local Testing

Unit tests for `claude-pr-gate` are executed using `pytest`:

```bash
pip install -r src/requirements-dev.txt
pytest tests/ -v
```

---

## 📄 License

[MIT](LICENSE) © Marc Rambow ([circularis.dev](https://circularis.dev))
