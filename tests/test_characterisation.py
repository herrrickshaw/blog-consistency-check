"""Assert the code reproduces the snapshot captured from the ORIGINAL (pre-refactor) code."""
import json
from pathlib import Path

from tests._snapshot import compute

ROOT = Path(__file__).resolve().parent.parent


def test_matches_original_behaviour_on_fixes_corpus():
    golden = json.loads((ROOT / "tests" / "golden_baseline.json").read_text())
    assert json.loads(json.dumps(compute(ROOT), sort_keys=True)) == golden
