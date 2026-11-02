"""The guide build: the overlay's anchors, and what the published page must not contain."""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "guide"))
import build_guide  # noqa: E402
import overlay  # noqa: E402

from tests.test_secrets import local_values  # noqa: E402

REPO = Path.home() / "splunky-finance"
REF = "origin/build-splunky-finance"


@pytest.fixture(scope="module")
def upstream():
    """The lab guide as the Splunky Finance branch tip has it. Skipped where the repo is absent,
    so the suite still runs on a box that only has the portal."""
    if not (REPO / ".git").exists():
        pytest.skip(f"{REPO} is not a checkout")
    result = subprocess.run(["git", "-C", str(REPO), "show", f"{REF}:docs/workshop-lab.md"],
                            capture_output=True, text=True)
    if result.returncode != 0:
        pytest.skip(f"cannot read the guide at {REF}")
    return result.stdout


def test_every_anchor_still_matches_the_upstream_guide(upstream):
    """This is the test that catches an upstream edit before a room full of people does."""
    overlaid = overlay.apply(upstream)
    assert overlaid != upstream


def test_the_overlay_takes_the_credentials_table_out_of_the_guide(upstream):
    overlaid = overlay.apply(upstream)
    for secret in ("AlexDemo1234!", "PresenterDemo1234!", "account `12345678`"):
        assert secret in upstream
        assert secret not in overlaid
    assert "Your lab details" in overlaid


def test_the_overlay_points_the_model_steps_at_the_card(upstream):
    overlaid = overlay.apply(upstream)
    assert "Custom (OpenAI-compatible)" in overlaid
    assert overlaid.count("*Your lab details*") >= 3
    # The gateway's address, the model and the key are never written into the markdown: they
    # come from /api/credentials behind the cookie. Checked against this box's real settings.
    for key, value in local_values().items():
        assert value not in overlaid, key


def test_the_overlay_replaces_the_judge_model_instruction(upstream):
    overlaid = overlay.apply(upstream)
    assert "**Use `gpt-4.1-mini` as the judge model.**" not in overlaid
    # The measured figure is kept, because it is the honest version of the claim.
    assert "measured on `gpt-4.1-mini`" in overlaid


def test_a_moved_anchor_fails_the_build_rather_than_dropping_a_section(upstream):
    mangled = upstream.replace("## Before you start", "## Before you begin")
    with pytest.raises(overlay.MissingAnchor):
        overlay.apply(mangled)


def test_headings_get_anchors_and_a_sidebar_in_document_order():
    html, nav = build_guide.add_heading_ids(
        "<h2>Step 1: Do the thing</h2><h3>A note</h3><h2>Step 2: Do the next</h2>")
    assert 'id="step-1-do-the-thing"' in html
    assert 'id="a-note"' in html
    assert nav == [{"id": "step-1-do-the-thing", "title": "Step 1: Do the thing"},
                   {"id": "step-2-do-the-next", "title": "Step 2: Do the next"}]


def test_a_repeated_heading_gets_its_own_anchor():
    html, nav = build_guide.add_heading_ids("<h2>Where to look</h2><h2>Where to look</h2>")
    assert 'id="where-to-look"' in html and 'id="where-to-look-2"' in html
    assert [item["id"] for item in nav] == ["where-to-look", "where-to-look-2"]


def test_screenshots_are_rewritten_to_local_files(tmp_path, monkeypatch):
    monkeypatch.setattr(build_guide, "IMAGES", tmp_path)
    (tmp_path / "abc-123.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    text = "![x](https://github.com/user-attachments/assets/abc-123)"
    images, missing = build_guide.collect_images(text, allow_fetch=False)
    assert images == {"abc-123": "abc-123.png"}
    assert missing == []


def test_a_missing_screenshot_is_reported_not_silently_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(build_guide, "IMAGES", tmp_path)
    images, missing = build_guide.collect_images(
        "![x](https://github.com/user-attachments/assets/nope-999)", allow_fetch=False)
    assert images == {} and missing == ["nope-999"]


def test_sections_are_split_onto_their_pages():
    html = ('<h1>Lab</h1><p>Intro.</p><hr />'
            '<h2 id="before-you-start">Before you start</h2><p>a</p><hr />'
            '<h2 id="step-3-x">Step 3: Connect it</h2><p>b</p>'
            '<h2 id="step-4-y">Step 4: Judge it</h2><p>c</p>'
            '<h2 id="troubleshooting">Troubleshooting</h2><p>d</p>'
            '<h2 id="new-thing">Something upstream added</h2><p>e</p>')
    intro, sections = build_guide.split_sections(html)
    assert intro == "<p>Intro.</p>"
    assert [(s["id"], s["group"], s["step"]) for s in sections] == [
        ("before-you-start", "briefing", None),
        ("step-3-x", "briefing", 3),
        ("step-4-y", "lab", 4),
        ("troubleshooting", "troubleshooting", None),
        ("new-thing", "lab", None),
    ]
    assert sections[1]["short"] == "Connect it"
    assert not sections[0]["html"].endswith("<hr />")


def test_every_upstream_section_lands_on_a_page(upstream):
    """A section that matched no page would silently vanish from the site."""
    html, _ = build_guide.add_heading_ids(build_guide.render(overlay.apply(upstream)))
    _, sections = build_guide.split_sections(html)
    groups = {s["group"] for s in sections}
    assert groups == {"briefing", "lab", "troubleshooting"}
    assert [s["step"] for s in sections if s["step"]] == list(range(1, 9))


def test_the_built_guide_in_this_checkout_has_no_credentials_in_it():
    built = Path(__file__).resolve().parent.parent / "app" / "generated" / "guide.json"
    if not built.exists():
        pytest.skip("guide not built")
    text = built.read_text()
    for secret in ("AlexDemo1234!", "PresenterDemo1234!"):
        assert secret not in text
    for key, value in local_values().items():
        assert value not in text, key


def test_the_placeholder_snippet_becomes_the_participants_own(upstream):
    """Step 4 shows the same filled-in block as My lab, never ENDPOINT_URL and YOUR_TOKEN."""
    assert "YOUR_TOKEN" in upstream
    overlaid = overlay.apply(upstream)
    for placeholder in ("ENDPOINT_URL", "YOUR_TOKEN", "LLM_MODEL_NAME"):
        assert placeholder not in overlaid
    assert "data-integration-snippet" in overlaid
    html, _ = build_guide.add_heading_ids(build_guide.render(overlaid))
    assert '<div class="live-snippet" data-integration-snippet></div>' in html


def test_step_four_shows_the_clean_integration_screenshot(upstream):
    """The upstream capture has hand-drawn example values, a made-up key among them."""
    overlaid = overlay.apply(upstream)
    assert "81b1aacf-b573-49ef-a7b4-6da76a4eea64" not in overlaid
    assert 'src="/static/img/galileo-custom-integration.png"' in overlaid
    image = Path(__file__).resolve().parent.parent / "app/static/img/galileo-custom-integration.png"
    assert image.exists()


def test_every_evaluator_names_the_judge_model(upstream):
    overlaid = overlay.apply(upstream)
    assert overlaid.count(overlay.PICK_NOW) == 3
    assert overlaid.count(overlay.PICKER_NOW) == 3
    assert "GPT-4.1 mini" not in overlaid
    assert "Select **Custom**" in overlaid


def test_a_repeated_sentence_that_changes_count_upstream_fails_the_build(upstream):
    """If an evaluator is added or dropped upstream, the build stops instead of half-applying."""
    first_only = upstream.replace(overlay.PICK_WAS, "Select the LLM model,", 1)
    with pytest.raises(overlay.MissingAnchor, match="expected 3"):
        overlay.apply(first_only)


def test_the_fault_table_is_followed_by_a_worked_example_in_order(upstream):
    overlaid = overlay.apply(upstream)
    example = overlaid.index("**A worked example: Incomplete Answer**")
    assert overlaid.index("| **Wrong Customer** |") < example < overlaid.index("Then set the scenario back")
    shots = [overlaid.index(f"/static/img/fault-incomplete-{n}") for n in ("1-enable", "2-ask", "3-galileo")]
    assert example < shots[0] < shots[1] < shots[2]
    images = Path(__file__).resolve().parent.parent / "app/static/img"
    for name in ("1-enable", "2-ask", "3-galileo"):
        assert (images / f"fault-incomplete-{name}.png").exists()


def test_the_fault_section_explains_why_failures_are_forced(upstream):
    overlaid = overlay.apply(upstream)
    section = overlaid.index("### Run one fault at a time")
    why = overlaid.index("**Why the failures are forced.**")
    assert section < why < overlaid.index("For each row: click")
    assert overlaid.count("### Run one fault at a time") == 1
