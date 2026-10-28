import json
from pathlib import Path


def test_researcher_console_shell_navigation_and_seed_fixture_are_wired():
    root = Path(__file__).parents[1] / "apps" / "researcher-console"
    html = (root / "index.html").read_text()
    app = (root / "src" / "main.ts").read_text()
    fixture = json.loads((root / "seed-fixtures.json").read_text())
    assert 'src="/src/main.ts"' in html
    assert 'mountExperienceRegistry' in app and 'mountStudyAuthoring' in app
    assert '["experiences", "Experiences"]' in app
    assert '["studies", "Studies"]' in app
    assert '["analytics", "Analytics"]' in app
    assert "Create E2E seed workspace" in app
    assert fixture["experience"]["allowed_origins"] == ["http://localhost:5173"]
    assert len(fixture["studies"]) == 2
    assert all(study["questions"] and study["aois"] and study["timing_rules"] for study in fixture["studies"])
    assert [study["gaze_required"] for study in fixture["studies"]] == [True, False]
    assert fixture["studies"][0]["aois"][0]["selector"] == "#study-content"
    participant_html = (Path(__file__).parents[1] / "apps" / "participant-demo" / "index.html").read_text()
    assert 'id="study-content" data-aoi="product-card"' in participant_html
    assert 'id="diagnostics"' in participant_html
    participant_css = (Path(__file__).parents[1] / "apps" / "participant-demo" / "style.css").read_text()
    assert "#study-content { width: 100vw;" in participant_css
