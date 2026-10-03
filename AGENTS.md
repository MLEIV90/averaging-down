# Project development rules

## Scope and quantitative integrity

- Treat this repository as a quantitative research project. Implement explicit specifications; do not invent or silently finalize financial assumptions.
- When a strategy, risk, portfolio, or execution choice is undefined, record it as an **OPEN QUESTION** in `RESEARCH_LOG.md`. Ask for a research decision before making it a definitive rule.
- Preserve time ordering. Features used for a decision at time *t* must not use information after *t*. Make signal, decision, and execution timestamps explicit when implementing strategy or backtest behavior. Do not assume execution at a close used to form that signal without an explicit execution model.
- Keep market data validation before feature calculation in the eventual integrated data flow. Record dataset provenance and assumptions needed to reproduce research results.
- Keep UI code separate from quantitative logic. The UI consumes engine results; it must not contain financial rules or independently implement a second version of indicators.
- Strategy and backtest entry points must remain usable without Streamlit.
- Do not add live broker orders, real-money execution integrations, or real execution endpoints.
- Do not claim that a strategy or result is validated based only on code existence or a passing software test.

## Engineering and tests

- Keep financial parameters centralized and configurable; avoid duplicating them as hardcoded values across business logic.
- Before implementing functionality, define deterministic tests for the specified behavior. Run relevant tests after changes and report the actual command and result. Never change quantitative behavior just to make a test pass without an explicit research decision.
- Unit tests must not depend on the Internet. Keep network-dependent tests clearly separated from deterministic tests as the test suite is organized.
- This repository's `pytest.ini` excludes tests marked `integration` from the default run. Run those separately with `python -m pytest -m integration` when network access is available.
- Do not install dependencies unless the task requires it. Keep direct runtime dependencies declared in `requirements.txt`.
- Prefer small, reviewable milestone changes. Update `CHANGELOG.md`; record hypotheses, experiments, results, limitations, decisions, and unresolved quantitative questions in `RESEARCH_LOG.md` when relevant.
- Use repository-root-relative commands unless the code has been made independent of the working directory.

## Git and completion reporting

- Use Conventional Commit prefixes (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`).
- Before a requested commit or push, inspect the diff and status for unintended files, generated data, virtual environments, and secrets. Never commit credentials or unnecessary datasets.
- Do not push a milestone if tests fail, a known regression remains, a secret is present, or the code is partially broken. Report the blocker and test output instead.
- For each completed milestone, report changed files, relevant fixes, tests and actual results, commit and hash, push status, remaining work, and OPEN QUESTIONS requiring a quantitative decision. Do not claim an action that was not completed.
