"""The headline's colours, sampled from Splunk's brand gradient."""
from app import pages


def test_the_gradient_runs_from_splunk_pink_to_splunk_orange():
    assert pages.splunk_colour(0) == "#EB008B"
    assert pages.splunk_colour(1) == "#F99D1C"
    assert pages.splunk_colour(0.58) == "#F05A22"
    assert pages.splunk_colour(-1) == "#EB008B" and pages.splunk_colour(2) == "#F99D1C"


def test_every_letter_gets_a_colour_and_the_lines_sweep_diagonally():
    lines = pages.gradient_lines(["Splunk Agent", "Observability"])
    assert ["".join(ch for ch, _ in line) for line in lines] == ["Splunk Agent", "Observability"]
    assert all(colour.startswith("#") and len(colour) == 7 for line in lines for _, colour in line)
    # The top line starts at the pink end and the bottom line finishes at the orange end, each
    # offset from the other, which is what makes the sweep read as diagonal.
    assert lines[0][0][1] == "#EB008B" and lines[1][-1][1] == "#F99D1C"
    assert lines[1][0][1] != "#EB008B" and lines[0][-1][1] != "#F99D1C"
