# Changelog

Notable repository changes are recorded here.

## [Unreleased]

### Added

- Project development and quantitative integrity rules in `AGENTS.md`.
- Initial repository baseline, limitations, and open research questions in `RESEARCH_LOG.md`.

### Changed

- Expanded setup and run instructions to cover the actual UI, data, EOD, backtest, and test entry points.
- Declared Plotly as a direct dependency because Streamlit pages import it directly.

### Known baseline limitations

- The vectorized backtest is not the EOD state-machine strategy and does not model costs or portfolio accounting.
- Some UI pages are placeholders, and not all `src/` modules are connected to a runtime workflow.
- The existing data test suite includes an Internet-dependent Yahoo Finance test.
