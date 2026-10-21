"""Parse unified Git diffs into simple, structured data.

The input is always treated as untrusted text: nothing in it is executed,
imported or evaluated. The parser only reads lines and string patterns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

MAX_INPUT_BYTES = 200_000  # ~200 KB, plenty for a typical pull request

HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
GIT_HEADER = re.compile(r"^diff --git a/(.*) b/(.*)$")

DEPENDENCY_FILES = {
    "requirements.txt", "requirements-dev.txt", "pyproject.toml", "setup.py",
    "setup.cfg", "pipfile", "pipfile.lock", "poetry.lock", "package.json",
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "gemfile", "gemfile.lock",
    "go.mod", "go.sum", "cargo.toml", "cargo.lock", "pom.xml", "build.gradle",
    "build.gradle.kts", "composer.json", "composer.lock", "makefile", "cmakelists.txt",
}
CONFIG_FILES = {"dockerfile", "procfile", "nginx.conf", ".dockerignore"}
CONFIG_EXTENSIONS = {".yml", ".yaml", ".toml", ".ini", ".cfg", ".conf", ".env", ".tf", ".tfvars"}
SOURCE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".kt", ".go", ".rb", ".php",
    ".cs", ".rs", ".swift", ".c", ".h", ".cpp", ".hpp", ".scala", ".sql", ".sh",
    ".vue", ".svelte",
}
DOC_EXTENSIONS = {".md", ".rst", ".txt", ".adoc"}


@dataclass
class FileChange:
    path: str
    old_path: str | None = None
    status: str = "modified"  # modified | added | deleted | renamed
    kind: str = "other"  # source | test | dependency | config | docs | other
    added_lines: list[str] = field(default_factory=list)
    removed_lines: list[str] = field(default_factory=list)

    @property
    def additions(self) -> int:
        return len(self.added_lines)

    @property
    def deletions(self) -> int:
        return len(self.removed_lines)


@dataclass
class ParsedDiff:
    files: list[FileChange] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def total_added(self) -> int:
        return sum(f.additions for f in self.files)

    @property
    def total_removed(self) -> int:
        return sum(f.deletions for f in self.files)


def validate_input(text: str) -> str | None:
    """Return a user-facing error message, or None if the input can be parsed."""
    if not text or not text.strip():
        return "Please paste a unified Git diff (for example, the output of `git diff`)."
    size = len(text.encode("utf-8"))
    if size > MAX_INPUT_BYTES:
        return (
            f"The diff is {size / 1000:.0f} KB, which exceeds the "
            f"{MAX_INPUT_BYTES // 1000} KB limit. Try analyzing a smaller set of files."
        )
    return None


def classify_path(path: str) -> str:
    """Guess what a file is for, based only on its path."""
    pure = PurePosixPath(path.lower())
    name, suffix = pure.name, pure.suffix
    parts = pure.parts[:-1]

    if (
        any(p in {"test", "tests", "__tests__", "spec"} for p in parts)
        or name.startswith("test_")
        or name in {"tests.py", "conftest.py"}
        or re.search(r"(_test|\.test|\.spec)\.\w+$", name)
    ):
        return "test"
    if name in DEPENDENCY_FILES or re.fullmatch(r"requirements[\w.-]*\.txt", name):
        return "dependency"
    if (
        name in CONFIG_FILES
        or name.startswith(".env")
        or name.startswith("docker-compose")
        or suffix in CONFIG_EXTENSIONS
    ):
        return "config"
    if suffix in SOURCE_EXTENSIONS:
        return "source"
    if suffix in DOC_EXTENSIONS or name in {"license", "changelog"}:
        return "docs"
    return "other"


def _clean_header_path(raw: str) -> str | None:
    """Turn '--- a/path\t<timestamp>' style values into 'path' (None for /dev/null)."""
    value = raw.split("\t", 1)[0].strip().strip('"')
    if value == "/dev/null":
        return None
    if value.startswith(("a/", "b/")):
        value = value[2:]
    return value


def _paths_from_git_header(line: str) -> tuple[str, str]:
    match = GIT_HEADER.match(line)
    if not match:
        rest = line[len("diff --git "):].strip()
        return rest, rest
    return match.group(1), match.group(2)


def parse_diff(text: str) -> ParsedDiff:
    """Parse unified diff text. Never raises on malformed input."""
    result = ParsedDiff()
    current: FileChange | None = None
    old_left = new_left = 0  # lines still expected in the current hunk
    in_hunk = False
    malformed_hunk = False  # header without line counts: read until the next header

    def start_file(path: str) -> FileChange:
        change = FileChange(path=path)
        result.files.append(change)
        return change

    def finish_hunk() -> None:
        nonlocal in_hunk, malformed_hunk
        if in_hunk and not malformed_hunk and (old_left > 0 or new_left > 0):
            result.warnings.append(
                f"The diff for '{current.path}' looks incomplete (a hunk ended early)."
            )
        in_hunk = malformed_hunk = False

    # Split on "\n" only: str.splitlines() would also split on form feeds and
    # other separators that can legitimately appear inside a line of code.
    lines = [line.removesuffix("\r") for line in (text or "").split("\n")]
    if lines and lines[-1] == "":
        lines.pop()
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1

        # Inside a hunk, the header's line counts tell us exactly how many
        # lines belong to it, so code like "--- comment" is never misread.
        if in_hunk and (malformed_hunk or old_left > 0 or new_left > 0):
            if line.startswith("+"):
                current.added_lines.append(line[1:])
                new_left -= 1
                continue
            if line.startswith("-"):
                current.removed_lines.append(line[1:])
                old_left -= 1
                continue
            if line.startswith(" ") or line == "":
                old_left -= 1
                new_left -= 1
                continue
            if line.startswith("\\"):  # "\ No newline at end of file"
                continue
            finish_hunk()  # unexpected line: fall through and treat as header
        elif in_hunk:
            if line.startswith("\\"):
                continue
            in_hunk = False

        if line.startswith("diff --git "):
            old, new = _paths_from_git_header(line)
            current = start_file(new)
            if old != new:
                current.old_path = old
        elif line.startswith("--- ") and i < len(lines) and lines[i].startswith("+++ "):
            old = _clean_header_path(line[4:])
            new = _clean_header_path(lines[i][4:])
            i += 1
            if current is None or current.added_lines or current.removed_lines or in_hunk:
                current = start_file(new or old or "unknown")
            current.path = new or old or current.path
            if old is None:
                current.status = "added"
            elif new is None:
                current.status = "deleted"
            elif old != new:
                current.old_path = old
        elif current is not None and line.startswith("new file mode"):
            current.status = "added"
        elif current is not None and line.startswith("deleted file mode"):
            current.status = "deleted"
        elif current is not None and line.startswith("rename from "):
            current.old_path = line[len("rename from "):].strip()
            current.status = "renamed"
        elif current is not None and line.startswith("rename to "):
            current.path = line[len("rename to "):].strip()
            current.status = "renamed"
        elif current is not None and line.startswith("@@"):
            finish_hunk()
            match = HUNK_HEADER.match(line)
            malformed_hunk = match is None
            if match:
                old_left = int(match.group(2)) if match.group(2) is not None else 1
                new_left = int(match.group(4)) if match.group(4) is not None else 1
            else:
                # Malformed header: count nothing, but keep reading until
                # the next header instead of crashing.
                result.warnings.append(f"Malformed hunk header in '{current.path}'.")
            in_hunk = True

    finish_hunk()

    for change in result.files:
        if change.status == "modified" and change.old_path and change.old_path != change.path:
            change.status = "renamed"
        change.kind = classify_path(change.path)
    return result
