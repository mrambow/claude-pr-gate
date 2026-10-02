# Claude PR Review Gate 🤖🛡️

[![CI](https://github.com/mrambow/claude-pr-gate/actions/workflows/ci.yml/badge.svg)](https://github.com/mrambow/claude-pr-gate/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A security-hardened, automated **PR Review Gatekeeper** GitHub Action powered by **Anthropic Claude**. Designed for high-reliability development teams and autonomous agent workflows adhering to the **Maker-Checker Principle**.

---

## ✨ Features

- 🔒 **Fail-Closed Security**: Only explicit `minor` findings pass. Unknown severities, parsing issues or model errors immediately block the PR.
- 🛡️ **Prompt-Injection Defense**: All untrusted inputs (PR Title, Description, Git Diff) are strictly sanitized against XML container escapes (e.g. `</diff>`, `</pr_title>`).
- 📂 **Base-Branch Isolation**: Project guidelines (e.g. `AGENTS.md`) are verified and loaded directly from `origin/$BASE_REF` via `git cat-file` and `git show` with locale-independent error handling. A PR cannot weaken its own evaluation rules.
- 🚫 **Anti-Tampering by Design**: Running as an external GitHub Action prevents PR branches from modifying the gatekeeper script or its dependencies.
- 🔍 **Traceability**: Review comments are explicitly tagged with the first 7 characters of the reviewed Commit-SHA (`PR_HEAD_SHA`).
- ⚡ **Highly Configurable**: Custom exclusion patterns for diffs (e.g. lockfiles, build artifacts), custom models, token limits, and guideline file paths.

---

## 🚀 Quickstart

Create a workflow file in your repository, e.g. `.github/workflows/claude-pr-gate.yml`:

```yaml
name: Claude PR Review Gate

on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review]

concurrency:
  group: claude-review-${{ github.event.pull_request.number }}
  cancel-in-progress: true

jobs:
  review:
    # Skip drafts, fork PRs (secrets unavailable), and dependabot
    if: >-
      github.event.pull_request.draft == false &&
      github.event.pull_request.head.repo.full_name == github.repository &&
      github.event.pull_request.user.login != 'dependabot[bot]'
    runs-on: ubuntu-latest
    timeout-minutes: 15
    permissions:
      contents: read
      pull-requests: write

    steps:
      - name: Checkout Code
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Claude PR Review Gate
        # Pin to a full commit SHA for maximum security and immutability
        uses: mrambow/claude-pr-gate@v1 # or @<commit-sha>
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
| `model` | Claude model name | No | `claude-opus-5-5` |
| `guidelines-file` | Path to project guidelines (relative to repo root) | No | `AGENTS.md` |
| `max-diff-chars` | Max diff character limit before truncation | No | `400000` |

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
