from diff_parser import MAX_INPUT_BYTES, parse_diff, validate_input

SIMPLE_DIFF = """\
diff --git a/src/app/utils.py b/src/app/utils.py
index 1111111..2222222 100644
--- a/src/app/utils.py
+++ b/src/app/utils.py
@@ -1,4 +1,5 @@
 def greet(name):
-    return "Hi " + name
+    return f"Hello, {name}!"
+

 def add(a, b):
"""


def test_validate_input_rejects_empty_and_whitespace():
    assert validate_input("") is not None
    assert validate_input("   \n\t  ") is not None


def test_validate_input_rejects_oversized_input():
    huge = "+" * (MAX_INPUT_BYTES + 1)
    message = validate_input(huge)
    assert message is not None
    assert "KB" in message


def test_validate_input_accepts_normal_diff():
    assert validate_input(SIMPLE_DIFF) is None


def test_extracts_path_and_line_counts():
    parsed = parse_diff(SIMPLE_DIFF)
    assert len(parsed.files) == 1
    change = parsed.files[0]
    assert change.path == "src/app/utils.py"
    assert change.status == "modified"
    assert change.additions == 2
    assert change.deletions == 1
    assert parsed.total_added == 2
    assert parsed.total_removed == 1


def test_headers_are_not_counted_as_code_lines():
    parsed = parse_diff(SIMPLE_DIFF)
    change = parsed.files[0]
    all_lines = change.added_lines + change.removed_lines
    assert not any(line.startswith(("++", "--", "@@")) for line in all_lines)
    assert '    return f"Hello, {name}!"' in change.added_lines
    assert '    return "Hi " + name' in change.removed_lines


def test_code_lines_that_look_like_headers_are_kept_inside_hunks():
    # A removed line whose content starts with "-- " (an SQL comment) must not
    # be mistaken for a "--- a/file" header.
    diff = """\
diff --git a/db/query.sql b/db/query.sql
--- a/db/query.sql
+++ b/db/query.sql
@@ -1,2 +1,2 @@
--- old comment
+-- new comment
 SELECT 1;
"""
    change = parse_diff(diff).files[0]
    assert change.removed_lines == ["-- old comment"]
    assert change.added_lines == ["-- new comment"]


def test_new_deleted_and_renamed_files():
    diff = """\
diff --git a/docs/new.md b/docs/new.md
new file mode 100644
--- /dev/null
+++ b/docs/new.md
@@ -0,0 +1,2 @@
+# Title
+Body
diff --git a/old.txt b/old.txt
deleted file mode 100644
--- a/old.txt
+++ /dev/null
@@ -1 +0,0 @@
-bye
diff --git a/src/a.py b/src/b.py
similarity index 100%
rename from src/a.py
rename to src/b.py
"""
    parsed = parse_diff(diff)
    by_path = {f.path: f for f in parsed.files}
    assert by_path["docs/new.md"].status == "added"
    assert by_path["docs/new.md"].additions == 2
    assert by_path["old.txt"].status == "deleted"
    assert by_path["old.txt"].deletions == 1
    renamed = by_path["src/b.py"]
    assert renamed.status == "renamed"
    assert renamed.old_path == "src/a.py"
    assert renamed.additions == 0 and renamed.deletions == 0


def test_file_kind_classification():
    paths = {
        "app/service.py": "source",
        "tests/test_service.py": "test",
        "web/button.test.tsx": "test",
        "requirements.txt": "dependency",
        "package.json": "dependency",
        "Dockerfile": "config",
        ".github/workflows/ci.yml": "config",
        ".env.example": "config",
        "README.md": "docs",
        "assets/logo.png": "other",
    }
    diff = "".join(
        f"diff --git a/{p} b/{p}\n--- a/{p}\n+++ b/{p}\n@@ -1 +1 @@\n-x\n+y\n"
        for p in paths
    )
    parsed = parse_diff(diff)
    assert {f.path: f.kind for f in parsed.files} == paths


def test_plain_unified_diff_without_git_header():
    diff = """\
--- a/config.yaml
+++ b/config.yaml
@@ -1 +1 @@
-debug: false
+debug: true
"""
    parsed = parse_diff(diff)
    assert [f.path for f in parsed.files] == ["config.yaml"]
    assert parsed.files[0].additions == 1


def test_truncated_hunk_is_handled_with_a_warning():
    diff = """\
diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1,10 +1,10 @@
-old = 1
+new = 1
"""
    parsed = parse_diff(diff)
    assert parsed.files[0].additions == 1
    assert any("incomplete" in w.lower() for w in parsed.warnings)


def test_text_without_file_changes_returns_no_files():
    parsed = parse_diff("this is just some text\nnot a diff at all\n")
    assert parsed.files == []


def test_metadata_only_diff_has_no_code_lines():
    diff = """\
diff --git a/script.sh b/script.sh
old mode 100644
new mode 100755
"""
    parsed = parse_diff(diff)
    assert len(parsed.files) == 1
    assert parsed.total_added == 0 and parsed.total_removed == 0


def test_unusual_file_names_do_not_crash():
    diff = """\
diff --git a/dir with spaces/ünïcødé file.py b/dir with spaces/ünïcødé file.py
--- a/dir with spaces/ünïcødé file.py
+++ b/dir with spaces/ünïcødé file.py
@@ -1 +1 @@
-a = 1
+a = 2
"""
    parsed = parse_diff(diff)
    assert parsed.files[0].path == "dir with spaces/ünïcødé file.py"
    assert parsed.files[0].kind == "source"


def test_unusual_line_separators_inside_code_do_not_break_hunks():
    # Form feeds and similar characters are ordinary content inside a line.
    diff = "--- a/a.py\n+++ b/a.py\n@@ -1,2 +1,1 @@\n a\x0cb\n-@login_required\n"
    change = parse_diff(diff).files[0]
    assert change.removed_lines == ["@login_required"]


def test_windows_line_endings_are_supported():
    diff = "--- a/a.py\r\n+++ b/a.py\r\n@@ -1 +1 @@\r\n-x = 1\r\n+x = 2\r\n"
    change = parse_diff(diff).files[0]
    assert change.path == "a.py"
    assert change.added_lines == ["x = 2"]


def test_malformed_hunk_header_gives_a_single_warning():
    diff = "--- a/a.py\n+++ b/a.py\n@@ bad @@\n-foo\n+bar\n"
    parsed = parse_diff(diff)
    assert len(parsed.warnings) == 1
    assert "Malformed" in parsed.warnings[0]


def test_common_test_file_names_are_recognized():
    diff = "".join(
        f"--- a/{p}\n+++ b/{p}\n@@ -1 +1 @@\n-x\n+y\n" for p in ["app/tests.py", "conftest.py"]
    )
    assert [f.kind for f in parse_diff(diff).files] == ["test", "test"]
