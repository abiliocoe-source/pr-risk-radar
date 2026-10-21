"""Deterministic, explainable risk scoring for parsed diffs.

Every rule below adds a fixed number of points at most once, so the score
is easy to explain: it is simply the sum of the triggered rules, capped at
100. The weights are heuristics chosen for this project, not measurements.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass, field

from diff_parser import FileChange, ParsedDiff

DISCLAIMER = (
    "This score is a rule-based heuristic that highlights changes worth a closer "
    "review. It is not the probability of a bug and not a security assessment."
)

# Category thresholds (inclusive lower bounds).
MEDIUM_THRESHOLD = 30
HIGH_THRESHOLD = 60

# Rule weights.
AUTH_POINTS = 20
DATABASE_POINTS = 15
DEPENDENCY_POINTS = 10
CONFIG_POINTS = 10
SIZE_MEDIUM_POINTS = 10  # more than SIZE_MEDIUM_LINES changed lines
SIZE_LARGE_POINTS = 20  # more than SIZE_LARGE_LINES (replaces the medium penalty)
SAFEGUARD_REMOVED_POINTS = 20
SAFEGUARD_DISABLED_POINTS = 10
SIZE_MEDIUM_LINES = 100
SIZE_LARGE_LINES = 300

MAX_EVIDENCE = 5
MAX_EVIDENCE_CHARS = 120

# Path patterns match whole path segments or name parts (split on / _ . -),
# so "auth/", "oauth2.py" or "user_permissions.py" match but "author.py" does not.
_SEP = r"(?:^|[/_.\-])"
_END = r"(?:[/_.\-]|$)"
AUTH_PATH = re.compile(
    _SEP + r"(auth|authn|authz|authenticat(e|ion|or)|authori[sz](e|ation|er)|login|logout|"
    r"permissions?|rbac|acl|oauth2?|jwt|"
    r"roles?|access[_\-]?control|security)" + _END,
    re.IGNORECASE,
)
DATABASE_PATH = re.compile(_SEP + r"(migrations?|alembic|schema|db)" + _END + r"|\.sql$", re.IGNORECASE)

# Code patterns target identifiers and call shapes, not single loose words.
AUTH_CODE = re.compile(
    r"\b(is_authenticated|login_required|permission_required|has_perms?|"
    r"has_permission|check_permissions?|require_role|requires_auth|authorize|"
    r"authenticate|is_admin|is_superuser|is_staff|verify_password|check_password|"
    r"access_token|refresh_token|jwt\.(encode|decode)|PermissionDenied|"
    r"Unauthorized|Forbidden|IsAuthenticated|IsAdminUser)\b"
    r"|\[Authorize\b|@(PreAuthorize|Secured|RolesAllowed)\b"
)
# SQL keywords must be upper case, so English like "select an option from"
# is ignored. Lower-case SQL is still caught through the query call shapes.
SQL_CODE = re.compile(
    r"\b(SELECT\b.+\bFROM|INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|"
    r"(ALTER|CREATE|DROP|TRUNCATE)\s+(TABLE|INDEX|COLUMN|VIEW))\b"
    r"|(\bcursor\.execute|\.executemany|\.raw|\bsession\.query|\bdb\.query|\bRunSQL)\s*\("
)
# Lines whose removal suggests a protection was taken away.
SAFEGUARD_CODE = re.compile(
    r"\b(login_required|permission_required|is_authenticated|has_perms?|"
    r"has_permission|check_permissions?|require_role|requires_auth|authorize|"
    r"csrf_protect|IsAuthenticated|IsAdminUser)\b"
    r"|\[Authorize\b|@(PreAuthorize|Secured|RolesAllowed)\b"
    r"|\b(validate\w*|sanitize\w*|escape)\s*\("
    r"|raise\s+(PermissionDenied|Unauthorized|Forbidden|ValidationError)"
    r"|abort\(\s*40[13]\s*\)"
)
# Added lines that explicitly switch a protection off.
SAFEGUARD_DISABLED_CODE = re.compile(
    r"verify\s*=\s*False|@csrf_exempt|\bAllowAny\b|ssl\._create_unverified_context"
    r"|rejectUnauthorized\s*:\s*false"
)

SUGGESTED_TESTS = {
    "auth": [
        "Test that unauthenticated users are rejected (e.g. 401 or redirect to login).",
        "Test that users without the required permission or role get a 403.",
        "Test that authorized users still have access after the change.",
    ],
    "database": [
        "Run migrations forward and backward against a copy of realistic data.",
        "Test changed queries with empty, typical and edge-case data.",
        "Check that query parameters are bound, not concatenated into SQL strings.",
    ],
    "dependencies": [
        "Run the full test suite with the updated dependencies installed from scratch.",
        "Review changelogs of upgraded packages for breaking changes.",
    ],
    "config": [
        "Verify the application starts with the new configuration in a staging-like environment.",
        "Check that required environment variables have safe defaults or clear errors.",
    ],
    "large_change": [
        "Consider splitting the change into smaller pull requests for easier review.",
        "Run integration or end-to-end tests that cover the affected areas.",
    ],
    "safeguard_removed": [
        "Add a regression test proving the removed check is enforced elsewhere, or restore it.",
        "Test invalid and malicious input against the affected code paths.",
    ],
    "safeguard_disabled": [
        "Confirm that disabling this protection is intentional and limited in scope.",
        "Test the code path with untrusted input or an invalid certificate/token.",
    ],
}


@dataclass
class Signal:
    id: str
    title: str
    points: int
    explanation: str
    evidence: list[str] = field(default_factory=list)


@dataclass
class RiskReport:
    score: int
    category: str
    signals: list[Signal]
    suggested_tests: list[str]
    testing_gap: str | None
    stats: dict
    warnings: list[str]
    disclaimer: str = DISCLAIMER

    def to_dict(self) -> dict:
        return asdict(self)


def categorize(score: int) -> str:
    if score >= HIGH_THRESHOLD:
        return "High"
    if score >= MEDIUM_THRESHOLD:
        return "Medium"
    return "Low"


def _snippet(path: str, sign: str, line: str) -> str:
    text = line.strip()
    if len(text) > MAX_EVIDENCE_CHARS:
        text = text[: MAX_EVIDENCE_CHARS - 1] + "…"
    return f"{path}: {sign} {text}"


def _scannable(files: list[FileChange]) -> list[FileChange]:
    """Files whose code lines are worth scanning (tests and docs are skipped)."""
    return [f for f in files if f.kind in {"source", "config", "dependency", "other"}]


def _code_matches(files: list[FileChange], pattern: re.Pattern, *, added=True, removed=True) -> list[str]:
    hits = []
    for change in _scannable(files):
        if removed:
            hits += [_snippet(change.path, "-", l) for l in change.removed_lines if pattern.search(l)]
        if added:
            hits += [_snippet(change.path, "+", l) for l in change.added_lines if pattern.search(l)]
    return hits


def _path_matches(files: list[FileChange], pattern: re.Pattern) -> list[str]:
    return [f"{f.path} (file path)" for f in _scannable(files) if pattern.search(f.path)]


def _removed_safeguards(files: list[FileChange]) -> list[str]:
    hits = []
    for change in _scannable(files):
        # A check that is removed and re-added (e.g. moved or re-indented)
        # within the same file is not counted as removed. Counting copies
        # means removing two checks and re-adding one still flags one.
        re_added = Counter(l.strip() for l in change.added_lines)
        for line in change.removed_lines:
            if not SAFEGUARD_CODE.search(line):
                continue
            if re_added[line.strip()] > 0:
                re_added[line.strip()] -= 1
            else:
                hits.append(_snippet(change.path, "-", line))
    return hits


def _signal(signal_id: str, title: str, points: int, explanation: str, evidence: list[str]) -> Signal:
    unique = list(dict.fromkeys(evidence))  # de-duplicate, keep order
    shown = unique[:MAX_EVIDENCE]
    if len(unique) > MAX_EVIDENCE:
        shown.append(f"… and {len(unique) - MAX_EVIDENCE} more")
    return Signal(signal_id, title, points, explanation, shown)


def analyze(parsed: ParsedDiff) -> RiskReport:
    files = parsed.files
    signals: list[Signal] = []

    auth = _path_matches(files, AUTH_PATH) + _code_matches(files, AUTH_CODE)
    if auth:
        signals.append(_signal(
            "auth", "Authentication or authorization", AUTH_POINTS,
            "The change touches login, permission or access-control code. Mistakes here "
            "can expose data or lock users out.", auth))

    database = _path_matches(files, DATABASE_PATH) + _code_matches(files, SQL_CODE)
    if database:
        signals.append(_signal(
            "database", "Database queries or migrations", DATABASE_POINTS,
            "SQL, query or migration code changed. These changes can affect data "
            "integrity and performance and are often hard to roll back.", database))

    dependencies = [f"{f.path} (dependency manifest)" for f in files if f.kind == "dependency"]
    if dependencies:
        signals.append(_signal(
            "dependencies", "Dependencies or build configuration", DEPENDENCY_POINTS,
            "Package manifests or build files changed. Upgrades can introduce breaking "
            "changes or new transitive dependencies.", dependencies))

    config = [f"{f.path} (configuration)" for f in files if f.kind == "config"]
    if config:
        signals.append(_signal(
            "config", "Environment, deployment or infrastructure", CONFIG_POINTS,
            "Configuration, deployment or infrastructure files changed. These often "
            "behave differently across environments.", config))

    changed = parsed.total_added + parsed.total_removed
    if changed > SIZE_LARGE_LINES:
        signals.append(Signal(
            "large_change", "Very large change", SIZE_LARGE_POINTS,
            f"{changed} lines changed (more than {SIZE_LARGE_LINES}). Large diffs are "
            "harder to review thoroughly."))
    elif changed > SIZE_MEDIUM_LINES:
        signals.append(Signal(
            "large_change", "Large change", SIZE_MEDIUM_POINTS,
            f"{changed} lines changed (more than {SIZE_MEDIUM_LINES}). Larger diffs are "
            "harder to review thoroughly."))

    removed = _removed_safeguards(files)
    if removed:
        signals.append(_signal(
            "safeguard_removed", "Security safeguard removed", SAFEGUARD_REMOVED_POINTS,
            "Lines that look like validation, authentication or permission checks were "
            "removed and not re-added elsewhere in the same file.", removed))

    disabled = _code_matches(files, SAFEGUARD_DISABLED_CODE, removed=False)
    if disabled:
        signals.append(_signal(
            "safeguard_disabled", "Security protection disabled", SAFEGUARD_DISABLED_POINTS,
            "Added code explicitly turns off a protection such as TLS verification or "
            "CSRF checks.", disabled))

    testing_gap = _testing_gap(files)
    suggested = [t for s in signals for t in SUGGESTED_TESTS.get(s.id, [])]
    if testing_gap:
        suggested.append("Add or update unit tests for the changed source files.")
    if not suggested:
        suggested.append("No specific risk patterns found. Run the existing test suite as usual.")

    score = max(0, min(100, sum(s.points for s in signals)))
    return RiskReport(
        score=score,
        category=categorize(score),
        signals=signals,
        suggested_tests=suggested,
        testing_gap=testing_gap,
        stats={
            "files_changed": len(files),
            "lines_added": parsed.total_added,
            "lines_removed": parsed.total_removed,
            "files": [
                {"path": f.path, "status": f.status, "kind": f.kind,
                 "added": f.additions, "removed": f.deletions}
                for f in files
            ],
        },
        warnings=list(parsed.warnings),
    )


def _testing_gap(files: list[FileChange]) -> str | None:
    """Advisory only: tests may exist elsewhere or be in another pull request."""
    sources = [f.path for f in files if f.kind == "source" and (f.additions or f.deletions)]
    if not sources or any(f.kind == "test" for f in files):
        return None
    return (
        f"{len(sources)} source file(s) changed but no test files appear in this diff. "
        "This does not prove tests are missing, but consider whether the change is covered."
    )
