from pathlib import Path

from app.render.canvas import PAPER_DOTS
from app.render.designs import SAMPLE_MORNING, morning_yannic

GOLDEN = Path(__file__).parent / "golden" / "design"


def test_morning_yannic_matches_the_node_reference_bit_for_bit():
    # tests/golden/design/b4-014.bin comes from design-lab/scripts/golden_b4014.js.
    bitmap = morning_yannic(SAMPLE_MORNING)
    expected = (GOLDEN / "b4-014.bin").read_bytes()
    assert bitmap.width == PAPER_DOTS == 512
    assert bitmap.height == 433
    assert bitmap.bits == expected


def test_missing_values_print_no_data_and_keep_the_layout():
    from dataclasses import replace

    live = morning_yannic(SAMPLE_MORNING)
    missing = morning_yannic(replace(SAMPLE_MORNING, stress=None, steps=None))
    assert missing.height == live.height
    assert missing.bits != live.bits
