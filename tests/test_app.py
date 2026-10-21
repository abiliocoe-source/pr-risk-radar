from pathlib import Path

from streamlit.testing.v1 import AppTest

from diff_parser import MAX_INPUT_BYTES

APP_PATH = str(Path(__file__).resolve().parent.parent / "app.py")


def run_app() -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    return at.run()


def analyze(at: AppTest, text: str) -> AppTest:
    at.text_area(key="diff_text").set_value(text)
    at.button(key="analyze").click()
    return at.run()


def test_app_renders_without_errors():
    at = run_app()
    assert not at.exception
    assert "PR Risk Radar" in at.title[0].value
    assert at.button(key="analyze")


def test_empty_input_shows_error():
    at = analyze(run_app(), "   ")
    assert not at.exception
    assert len(at.error) == 1
    assert len(at.metric) == 0


def test_oversized_input_shows_error():
    at = analyze(run_app(), "+" * (MAX_INPUT_BYTES + 10))
    assert not at.exception
    assert "limit" in at.error[0].value


def test_non_diff_text_shows_helpful_error():
    at = analyze(run_app(), "hello, this is not a diff")
    assert not at.exception
    assert "No file changes" in at.error[0].value


def test_selecting_example_and_analyzing_shows_results():
    at = run_app()
    at.selectbox(key="example").select("Authentication / permission change").run()
    assert "auth" in at.text_area(key="diff_text").value
    at.button(key="analyze").click().run()
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Risk score"] == "65 / 100"
    assert metrics["Category"] == "High"
    # The testing-gap advisory is shown separately as a warning.
    assert any("no test files" in w.value for w in at.warning)


def test_low_risk_example_has_no_testing_warning():
    at = run_app()
    at.selectbox(key="example").select("Low risk: small feature").run()
    at.button(key="analyze").click().run()
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Category"] == "Low"
    assert not any("no test files" in w.value for w in at.warning)


def test_loading_an_example_clears_previous_error():
    at = analyze(run_app(), "")
    assert len(at.error) == 1
    at.selectbox(key="example").select("Low risk: small feature").run()
    assert len(at.error) == 0
