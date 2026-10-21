from pathlib import Path

import pytest

from diff_parser import parse_diff
from risk_engine import analyze, categorize

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def make_diff(path: str, added: list[str] = (), removed: list[str] = ()) -> str:
    """Build a minimal single-file unified diff for tests."""
    body = [f"-{line}" for line in removed] + [f"+{line}" for line in added]
    return (
        f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
        f"@@ -1,{len(removed)} +1,{len(added)} @@\n" + "\n".join(body) + "\n"
    )


def analyze_text(text: str):
    return analyze(parse_diff(text))


def signal_ids(report) -> set[str]:
    return {s.id for s in report.signals}


@pytest.mark.parametrize(
    "score, expected",
    [(0, "Low"), (29, "Low"), (30, "Medium"), (59, "Medium"), (60, "High"), (100, "High")],
)
def test_category_boundaries(score, expected):
    assert categorize(score) == expected


def test_empty_diff_scores_zero():
    report = analyze_text("")
    assert report.score == 0
    assert report.category == "Low"
    assert report.signals == []


def test_low_risk_example():
    report = analyze_text((EXAMPLES / "low_risk.diff").read_text())
    assert report.category == "Low"
    assert report.testing_gap is None


def test_auth_example_is_high_risk():
    report = analyze_text((EXAMPLES / "auth_change.diff").read_text())
    assert report.category == "High"
    assert {"auth", "safeguard_removed"} <= signal_ids(report)


def test_dependency_example_is_medium_risk():
    report = analyze_text((EXAMPLES / "dependency_change.diff").read_text())
    assert report.category == "Medium"
    assert {"dependencies", "database"} <= signal_ids(report)


def test_auth_signal_from_code_lines():
    report = analyze_text(make_diff("app/views.py", added=["    if user.has_permission('edit'):"]))
    assert "auth" in signal_ids(report)


def test_auth_signal_from_file_path():
    report = analyze_text(make_diff("src/auth/tokens.py", added=["TTL = 60"]))
    assert "auth" in signal_ids(report)


def test_single_unrelated_word_does_not_trigger_auth():
    # "author" and "authentic" in prose-like code should not count as auth changes.
    report = analyze_text(make_diff("app/books.py", added=['    author = "Jane"', "    authentic = True"]))
    assert "auth" not in signal_ids(report)


@pytest.mark.parametrize("path", ["app/authentication.py", "app/oauth2.py", "src/authorization/policy.py"])
def test_auth_signal_from_common_auth_file_names(path):
    assert "auth" in signal_ids(analyze_text(make_diff(path, added=["TTL = 60"])))


def test_removing_framework_permission_class_is_detected():
    report = analyze_text(
        make_diff("app/views.py", removed=["    permission_classes = [IsAuthenticated]"],
                  added=["    permission_classes = []"])
    )
    assert {"auth", "safeguard_removed"} <= signal_ids(report)


def test_test_file_paths_do_not_raise_risk():
    report = analyze_text(make_diff("tests/test_permissions.py", added=["assert user.has_permission('x')"]))
    assert report.signals == []


def test_english_text_is_not_mistaken_for_sql():
    report = analyze_text(make_diff("app/ui.py", added=["# Select an option from the dropdown", 'msg = "delete from cache"']))
    assert "database" not in signal_ids(report)


def test_database_signal_from_sql():
    report = analyze_text(
        make_diff("app/repo.py", added=['    cursor.execute("SELECT id FROM users WHERE id = %s", (uid,))'])
    )
    assert "database" in signal_ids(report)


def test_database_signal_from_migration_path():
    report = analyze_text(make_diff("migrations/0002_add_field.py", added=["x = 1"]))
    assert "database" in signal_ids(report)


def test_removed_safeguard_detected():
    report = analyze_text(make_diff("app/views.py", removed=["@login_required"], added=["def view(request):"]))
    assert "safeguard_removed" in signal_ids(report)


def test_disabled_safeguard_detected():
    report = analyze_text(make_diff("app/client.py", added=["resp = requests.get(url, verify=False)"]))
    assert "safeguard_disabled" in signal_ids(report)


def test_moved_safeguard_is_not_flagged_as_removed():
    # The same check is removed in one place and re-added in another.
    report = analyze_text(make_diff("app/views.py", removed=["    @login_required"], added=["@login_required"]))
    assert "safeguard_removed" not in signal_ids(report)


def test_removed_safeguard_is_flagged_even_if_same_line_added_once_elsewhere():
    # Two checks removed, only one re-added: one endpoint lost its protection.
    report = analyze_text(
        make_diff("app/views.py", removed=["@login_required", "@login_required"], added=["@login_required"])
    )
    assert "safeguard_removed" in signal_ids(report)


def test_matches_in_docs_are_ignored():
    report = analyze_text(make_diff("docs/guide.md", added=["Use @login_required and SELECT * FROM users"]))
    assert "auth" not in signal_ids(report)
    assert "database" not in signal_ids(report)


def test_testing_gap_warning_when_source_changes_without_tests():
    report = analyze_text(make_diff("app/service.py", added=["x = 1"]))
    assert report.testing_gap is not None


def test_no_testing_gap_when_tests_are_included():
    text = make_diff("app/service.py", added=["x = 1"]) + make_diff("tests/test_service.py", added=["assert True"])
    assert analyze_text(text).testing_gap is None


def test_size_penalties_do_not_stack():
    medium = analyze_text(make_diff("app/a.py", added=[f"v{i} = {i}" for i in range(150)]))
    large = analyze_text(make_diff("app/a.py", added=[f"v{i} = {i}" for i in range(350)]))
    assert medium.score == 10
    assert large.score == 20
    assert [s.id for s in large.signals] == ["large_change"]


def test_score_is_capped_at_100():
    parts = [
        make_diff("src/auth/login.py", removed=["@login_required", "validate_token(token)"], added=["pass"]),
        make_diff("db/migrations/001.sql", added=["ALTER TABLE users ADD COLUMN role TEXT;"]),
        make_diff("requirements.txt", added=["django==5.0"]),
        make_diff("Dockerfile", added=["FROM python:3.12"]),
        make_diff("app/client.py", added=["requests.get(url, verify=False)"]),
        make_diff("app/big.py", added=[f"v{i} = {i}" for i in range(400)]),
    ]
    report = analyze_text("".join(parts))
    raw = sum(s.points for s in report.signals)
    assert raw > 100
    assert report.score == 100
    assert report.category == "High"


def test_every_scoring_signal_has_explanation():
    report = analyze_text((EXAMPLES / "auth_change.diff").read_text())
    for signal in report.signals:
        assert signal.points >= 0
        assert signal.explanation
    assert report.score == min(100, sum(s.points for s in report.signals))


def test_suggested_tests_follow_detected_signals():
    report = analyze_text((EXAMPLES / "auth_change.diff").read_text())
    joined = " ".join(report.suggested_tests).lower()
    assert "permission" in joined or "unauthorized" in joined


def test_scoring_is_deterministic():
    text = (EXAMPLES / "dependency_change.diff").read_text()
    assert analyze_text(text).to_dict() == analyze_text(text).to_dict()


def test_report_is_json_serializable():
    import json

    report = analyze_text((EXAMPLES / "auth_change.diff").read_text())
    data = json.loads(json.dumps(report.to_dict()))
    assert data["score"] == report.score
    assert "disclaimer" in data
