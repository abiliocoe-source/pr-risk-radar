# Repository setup notes

## Short description (GitHub "About" field)

Rule-based, explainable risk estimates for pasted Git diffs. Built with Python and Streamlit.

## Topics

`python` `streamlit` `git` `diff` `code-review` `pull-request` `risk-analysis` `static-analysis` `pytest` `developer-tools` `portfolio-project`

## Suggested pinned-repo blurb (profile / README intro)

PR Risk Radar reads a unified Git diff and explains which changes deserve extra review:
authentication, database, dependencies, configuration, size and removed safeguards.
Every point of the score is traceable to a documented rule. Educational project: the score
is a heuristic, not a bug probability or a security assessment.

## Interview talking points

- Separation of concerns: parser, scoring engine and UI are independent and tested separately.
- Explainability: deterministic rules with documented weights instead of a black box.
- Safety: pasted text is untrusted, never executed, and shown as plain code in the UI.
- Testing: pytest unit tests plus Streamlit AppTest, run in CI on Python 3.11-3.13.

## Before publishing

- Replace the placeholder name in `LICENSE`.
- Record `docs/demo.gif` and enable the image line in the README Demo section.
- Check the first GitHub Actions run after the first push.
