"""Streamlit interface for PR Risk Radar.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from diff_parser import MAX_INPUT_BYTES, parse_diff, validate_input
from risk_engine import DISCLAIMER, RiskReport, analyze

EXAMPLES_DIR = Path(__file__).resolve().parent / "examples"
CUSTOM = "Paste your own diff"
EXAMPLES = {
    "Low risk: small feature": "low_risk.diff",
    "Authentication / permission change": "auth_change.diff",
    "Dependency and database change": "dependency_change.diff",
}
CATEGORY_COLORS = {"Low": "green", "Medium": "orange", "High": "red"}


def load_example() -> None:
    """Callback: copy the chosen example into the text area."""
    choice = st.session_state["example"]
    if choice in EXAMPLES:
        st.session_state["diff_text"] = (EXAMPLES_DIR / EXAMPLES[choice]).read_text(encoding="utf-8")
    st.session_state.pop("report", None)
    st.session_state.pop("error", None)


def run_analysis() -> None:
    """Callback: validate, parse and score the current input."""
    st.session_state.pop("report", None)
    st.session_state.pop("error", None)
    text = st.session_state.get("diff_text", "")
    error = validate_input(text)
    if error is None:
        parsed = parse_diff(text)
        if not parsed.files:
            error = (
                "No file changes were recognized. Make sure you pasted a unified diff "
                "that contains lines such as `diff --git a/... b/...` or `--- a/...` / `+++ b/...`."
            )
        else:
            st.session_state["report"] = analyze(parsed)
    st.session_state["error"] = error


def render_report(report: RiskReport) -> None:
    stats = report.stats
    color = CATEGORY_COLORS[report.category]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Risk score", f"{report.score} / 100")
    col2.metric("Category", report.category)
    col3.metric("Files changed", stats["files_changed"])
    col4.metric("Lines", f"+{stats['lines_added']} / -{stats['lines_removed']}")
    st.markdown(f":{color}-background[**{report.category} risk**] · {DISCLAIMER}")

    if report.warnings:
        # Warnings quote file paths from the diff, so show them as plain text.
        st.caption("Parser notes")
        st.code("\n".join(report.warnings), language=None)
    if report.testing_gap:
        st.warning(f"Possible testing gap: {report.testing_gap}")

    left, right = st.columns([3, 2], gap="large")
    with left:
        st.subheader("Risk signals")
        if not report.signals:
            st.write("No risk rules matched this diff.")
        for signal in report.signals:
            with st.container(border=True):
                st.markdown(f"**{signal.title}** · +{signal.points} points")
                st.caption(signal.explanation)
                if signal.evidence:
                    # Evidence is untrusted text from the diff: show it as code,
                    # never as Markdown or HTML.
                    st.code("\n".join(signal.evidence), language=None)
    with right:
        st.subheader("Suggested tests")
        for test in report.suggested_tests:
            st.markdown(f"- {test}")

    st.subheader("Changed files")
    st.dataframe(stats["files"], hide_index=True)

    st.download_button(
        "Download analysis (JSON)",
        data=json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
        file_name="pr-risk-radar-report.json",
        mime="application/json",
    )


def main() -> None:
    st.set_page_config(page_title="PR Risk Radar", page_icon="🛰️", layout="wide")
    st.title("PR Risk Radar")
    st.caption(
        "Paste a unified Git diff to get a transparent, rule-based estimate of which "
        "changes deserve extra review. Nothing you paste is executed or stored."
    )

    st.selectbox("Example diffs", [CUSTOM, *EXAMPLES], key="example", on_change=load_example)
    st.text_area(
        "Unified diff",
        key="diff_text",
        height=320,
        placeholder="diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new",
        help=f"Output of `git diff` or a pull request .diff file, up to {MAX_INPUT_BYTES // 1000} KB.",
    )
    st.button("Analyze", key="analyze", type="primary", on_click=run_analysis)

    if st.session_state.get("error"):
        st.error(st.session_state["error"])
    elif "report" in st.session_state:
        st.divider()
        render_report(st.session_state["report"])

    with st.expander("How scoring works and its limitations"):
        st.markdown(
            """
- Each rule adds a fixed number of points once: authentication/permissions **+20**,
  database/SQL/migrations **+15**, dependencies/build files **+10**,
  configuration/infrastructure **+10**, more than 100 changed lines **+10**
  (more than 300: **+20** instead), removed security checks **+20**,
  explicitly disabled protections **+10**. The total is capped at 100.
- Categories: **Low** 0–29, **Medium** 30–59, **High** 60–100.
- Matching uses file paths and regular expressions on added/removed lines only.
  It does not understand program semantics, so it can miss risks or flag harmless code.
- The testing-gap warning only means no test files appear in *this* diff.
- Use the result as a prompt for review, not as a verdict.
"""
        )


main()
