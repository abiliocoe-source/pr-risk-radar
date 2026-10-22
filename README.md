# PR Risk Radar

PR Risk Radar is a small Streamlit app that reads a pasted Git diff and gives a
transparent, rule-based estimate of how much extra review the change deserves.
Every point in the score is tied to a rule you can read, and the app explains
which lines triggered it.

> This is an educational portfolio project. The score is a heuristic that
> highlights changes worth a closer look. It is **not** the probability of a
> bug and **not** a security assessment.

##Try it live →

Now deployed, on: **https://pr-risk-radar.streamlit.app/** **!**

## The problem

In a busy code review, a one-line change to a permission check can look just as
harmless as a one-line typo fix. PR Risk Radar points reviewers at the parts of
a diff that usually need more care: authentication and permissions, database
queries and migrations, dependencies, configuration, very large changes, and
removed safety checks.

## Features

- Paste a unified diff, such as the output of `git diff` or a GitHub pull request `.diff` file.
- Three built-in example diffs, so you can try it without a repository.
- Parses changed files, added and removed lines, renames, new and deleted files,
  and incomplete diffs, without ever executing the pasted text.
- Classifies files as source, test, dependency, config, docs or other.
- Deterministic score from 0 to 100 with a Low / Medium / High category.
- Each risk signal shows its points, an explanation and the matching lines.
- Suggested tests based on the signals that fired.
- A separate, advisory warning when source files change without any test files.
- JSON export of the full analysis.
- Clear messages for empty, invalid or oversized (> 200 KB) input.

## Scoring model

Each rule adds its points **at most once**, no matter how many lines match, so
a big auth refactor is not scored as twenty separate auth changes. The final
score is the sum of the triggered rules, capped at 100 (it can never be
negative).

| Rule | Points | Triggered by |
| --- | --- | --- |
| Authentication / authorization | +20 | Paths such as `auth/`, `authentication.py`, `oauth2.py`, `login`, `permissions`, `rbac`, `jwt`, or code such as `login_required`, `has_permission`, `IsAuthenticated`, `@PreAuthorize`, `PermissionDenied` |
| Database / SQL / migrations | +15 | Paths such as `migrations/`, `alembic/`, `*.sql`, or code such as `SELECT … FROM`, `ALTER TABLE`, `cursor.execute(`, `RunSQL(` |
| Dependencies / build files | +10 | `requirements.txt`, `pyproject.toml`, `package.json`, lock files, `go.mod`, `Makefile`, … |
| Environment / deployment / infrastructure | +10 | `Dockerfile`, `docker-compose*.yml`, `.env*`, `*.yml`, `*.toml`, `*.tf`, CI workflows, … |
| Large change | +10 | More than 100 changed lines (added + removed) |
| Very large change | +20 | More than 300 changed lines (replaces the +10 above) |
| Security safeguard removed | +20 | A removed line looks like an access check or validation (`@login_required`, `IsAuthenticated`, `raise PermissionDenied`, `validate_…(`, `abort(403)`) and is not re-added in that file |
| Security protection disabled | +10 | An added line explicitly turns a protection off (`verify=False`, `@csrf_exempt`, `AllowAny`) |
| Testing gap (advisory) | 0 | Source files changed but no test files appear in the diff |

Categories: **Low** 0–29, **Medium** 30–59, **High** 60–100.

A few deliberate choices keep the rules targeted:

- Only added and removed lines are scanned. Diff headers (`diff --git`, `---`,
  `+++`, `@@`) and unchanged context lines are not.
- Test and documentation files are not scanned (neither paths nor lines), so
  a README that mentions `SELECT * FROM users` or a new `tests/test_permissions.py`
  does not raise the score.
- Code patterns match identifiers and call shapes (`has_permission`,
  `cursor.execute(`), not loose words, so `author = "Jane"` does not count as
  an auth change.
- The testing-gap warning adds no points, because tests may live in another
  pull request.

These weights are starting values picked for this project, not measurements.
They live as named constants at the top of `risk_engine.py`.

## Architecture

```
pr-risk-radar/
├── app.py              # Streamlit UI: input, examples, results, JSON export
├── diff_parser.py      # Text -> ParsedDiff (files, lines, kinds, warnings)
├── risk_engine.py      # ParsedDiff -> RiskReport (score, signals, tests)
├── examples/           # Three sample diffs used by the UI and the tests
├── tests/              # pytest + Streamlit AppTest
├── .streamlit/         # Theme color, usage statistics off
└── .github/workflows/  # CI: install and run tests on push and pull request
```

The flow is one-directional: `app.py` calls `validate_input` and `parse_diff`
from `diff_parser.py`, passes the result to `analyze` in `risk_engine.py`, and
renders the returned `RiskReport`. The parser knows nothing about risk, and the
engine knows nothing about Streamlit, so each part can be tested on its own.

## Getting started

Requires Python 3.11 or newer.

```bash
cd pr-risk-radar
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Streamlit prints a local URL (usually http://localhost:8501). Pick an example
from the dropdown, or paste your own diff, then click **Analyze**.

To analyze your own work:

```bash
git diff main...my-branch > my-change.diff
```

Then paste the file contents into the app.

## Running the tests

```bash
python -m pytest
```

The suite covers the parser (paths, line counts, headers, renames, truncated
and malformed input), the risk engine (each rule, category boundaries, the
100-point cap, determinism) and the UI through Streamlit's `AppTest`
(rendering, error messages, analyzing an example). The GitHub Actions workflow
in `.github/workflows/tests.yml` runs the same command on Python 3.11, 3.12 and
3.13 for every push and pull request.

## Example use cases

- **Before requesting review:** check whether your branch touches areas the
  team considers sensitive, and add the suggested tests first.
- **As a reviewer:** start with the files and lines listed under each signal.
- **Learning:** compare the three examples to see how each rule contributes.

## Limitations

- Pattern matching only. The tool does not understand program semantics, so it
  can miss real risks and flag harmless code.
- Rules are tuned mostly for Python and common web-framework names; other
  languages are covered only partly.
- SQL keywords are matched only in upper case (to avoid flagging English text),
  so lower-case SQL is detected only through calls like `cursor.execute(`.
- The testing-gap warning only looks at this diff, not at the rest of the repository.
- Binary files are listed but not analyzed.
- Input is limited to 200 KB.

## Possible improvements

- Load rules and weights from a config file so teams can tune them.
- Accept a GitHub pull request URL and fetch the diff.
- Language-aware rules (for example, Java Spring Security or Rails `before_action`).
- Show the matched lines in the context of their hunk.

## License

Released under the [MIT License](LICENSE). The copyright holder name in `LICENSE` is a placeholder to be replaced with the author's name.
