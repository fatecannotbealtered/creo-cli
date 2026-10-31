"""Skill evidence bookkeeping: review prompts must not become invented acceptance."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "creo-cli"


def test_historical_and_new_review_prompts_are_all_unexecuted():
    prompts = json.loads((SKILL / "test-prompts.json").read_text(encoding="utf-8"))
    record = json.loads((SKILL / "evaluation-results.json").read_text(encoding="utf-8"))
    assert len(prompts) == record["review_prompts"]["count"]
    assert record["review_prompts"]["historical_count"] == 28
    assert len(prompts[:28]) == 28
    assert len(prompts[28:]) == record["review_prompts"]["native_display_candidate_added_count"]
    assert all(row["executed_across_models"] is False for row in prompts)
    assert len({row["id"] for row in prompts}) == len(prompts)
    assert record["actual_runs"] == []


def test_new_skill_reference_links_resolve_in_the_complete_package_tree():
    for relative in (
        "reference/presentation.md",
        "../../docs/NATIVE-APPEARANCE-DISPLAY.md",
        "../../docs/ACTIVATION-CONTEXT-BLOCKER.md",
        "../../docs/STARTUP-NATIVE.md",
        "../../docs/HEADLESS-SUPPORT.md",
        "../../examples/engineering/Invoke-CreoCli.md",
    ):
        assert (SKILL / relative).resolve().is_file()
