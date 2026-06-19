import ui_components as ui


def capture_markdown(monkeypatch):
    rendered = []
    monkeypatch.setattr(ui.st, "markdown", lambda body, **kwargs: rendered.append(body))
    return rendered


def test_metric_card_renders_without_error(monkeypatch):
    rendered = capture_markdown(monkeypatch)
    html = ui.render_metric_card("Portfolio value", "€12,345", "+2.1%", "positive")
    assert rendered and "metric-card" in html and "€12,345" in html


def test_status_pill_supports_all_tones(monkeypatch):
    capture_markdown(monkeypatch)
    for tone in ["neutral", "info", "positive", "success", "warning", "negative", "danger"]:
        html = ui.render_status_pill("Status", tone)
        assert "status-pill" in html


def test_data_quality_badge_supports_confidence_levels(monkeypatch):
    capture_markdown(monkeypatch)
    high = ui.render_data_quality_badge("High confidence")
    medium = ui.render_data_quality_badge("Medium confidence")
    low = ui.render_data_quality_badge("Low confidence")
    assert "success-pill" in high
    assert "warning-pill" in medium
    assert "danger-pill" in low


def test_recommendation_card_handles_missing_fields_and_escapes_html(monkeypatch):
    rendered = capture_markdown(monkeypatch)
    html = ui.render_recommendation_card(instrument="<Unknown>")
    assert rendered and "recommendation-card" in html
    assert "&lt;Unknown&gt;" in html and "No reason supplied" in html


def test_concise_public_component_helpers(monkeypatch):
    rendered = capture_markdown(monkeypatch)
    ui.page_header("Market", "Readable evidence")
    ui.action_card("Refresh", "Update market evidence", "Refresh now")
    ui.progress_step("Prices", "Done")
    assert len(rendered) == 3
