"""Related dirty source state is independent of restored render/image delivery."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from creo_cli import driver, operations
from tests import test_native_display_cli as presentation_fixture
from tests.test_features import Built


class RenderRelatedPersistence(Built):
    repeated_source = presentation_fixture.NativePresentationHTTP.repeated_source

    def render_case(self, *, source_dirty=True, owner_dirty=False):
        source, owner = self.repeated_source()
        source["modified"], owner["modified"] = source_dirty, owner_dirty
        answer = self.gated(
            "artifact",
            "render",
            "--model",
            "holdout.asm",
            "--view",
            "current",
            "--output",
            "related-dirty.jpg",
        )["data"]
        receipt = answer["receipt"]
        with patch.dict("os.environ", self.env, clear=True):
            run = operations.get(receipt["operation_id"])
        binding = deepcopy(run["driver_plan"]["base_snapshot"]["extensions"]["creo"]["observation"])
        plan = SimpleNamespace(
            op="model.render", target="holdout.asm", binding=binding, retained_only=True
        )
        return answer, run, plan, source, owner

    def test_clean_owner_dirty_shared_source_stays_unsaved_after_successful_render(self):
        answer, _, _, source, owner = self.render_case()
        receipt = answer["receipt"]
        self.assertEqual(receipt["outcome"]["persistence"], "unsaved")
        self.assertEqual(receipt["outcome"]["change"], "not_applied")
        self.assertEqual(receipt["outcome"]["verification"]["status"], "passed")
        self.assertTrue(answer["result"]["published"])
        self.assertTrue(source["modified"])
        self.assertFalse(owner["modified"])
        self.assertEqual(self.world.ops().count("model.render"), 1)
        self.assertNotIn("model.save", self.world.ops())
        basis = receipt["extensions"]["creo"]["render_persistence"]
        self.assertEqual(basis["source_modified"], {"block.prt": True})
        self.assertFalse(basis["saved_display_persistence_verified"])

    def test_clean_owner_and_all_source_parts_remain_unchanged(self):
        answer, _, _, _, _ = self.render_case(source_dirty=False)
        self.assertEqual(answer["receipt"]["outcome"]["persistence"], "unchanged")
        self.assertTrue(answer["result"]["published"])

    def test_dirty_owner_keeps_existing_unsaved_semantics(self):
        answer, _, _, _, _ = self.render_case(source_dirty=False, owner_dirty=True)
        self.assertEqual(answer["receipt"]["outcome"]["persistence"], "unsaved")

    def test_known_not_started_uses_complete_prior_without_losing_source_dirty(self):
        _, run, plan, _, _ = self.render_case()
        run = deepcopy(run)
        run["status"] = "failed_before_write"
        run.pop("driver_render", None)
        run.pop("driver_effect_readback", None)
        before = deepcopy(plan.binding)
        with patch.dict("os.environ", self.env, clear=True):
            receipt = driver.make_receipt(run, plan)
        self.assertEqual(receipt["outcome"]["persistence"], "unsaved")
        self.assertEqual(plan.binding, before)


@pytest.mark.parametrize("missing", ("map", "source", "modified", "nonbool", "complete", "owner"))
def test_incomplete_render_modified_observation_cannot_be_unchanged(missing):
    case = RenderRelatedPersistence()
    case.setUp()
    try:
        _, run, plan, _, _ = case.render_case()
        run = deepcopy(run)
        run.pop("driver_render", None)
        actual = run["driver_effect_readback"]["presentation"]
        if missing == "map":
            actual.pop("native_part_appearances")
        elif missing == "source":
            actual["native_part_appearances"].pop("block.prt")
        elif missing == "modified":
            actual["native_part_appearances"]["block.prt"].pop("modified")
        elif missing == "nonbool":
            actual["native_part_appearances"]["block.prt"]["modified"] = None
        elif missing == "complete":
            actual["native_part_appearances"]["block.prt"]["complete"] = False
        else:
            actual.pop("modified")
        original = deepcopy(actual)
        with patch.dict("os.environ", case.env, clear=True):
            receipt = driver.make_receipt(run, plan)
        assert receipt["outcome"]["persistence"] == "unknown"
        assert run["driver_effect_readback"]["presentation"] == original
    finally:
        case.doCleanups()
