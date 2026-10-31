"""A child reader cannot reset the confirmed task's wall-clock deadline."""

import os
from unittest.mock import patch

import pytest

from creo_cli import timing
from creo_cli.core import Error
from creo_cli.transport import Client
from tests import test_features as building_fixture


def test_nested_clients_share_the_invocation_deadline():
    with patch("time.monotonic", return_value=100.0):
        with timing.command("workflow run", 20):
            first = Client(20)
            with patch("time.monotonic", return_value=115.0):
                second = Client(20)
                assert first.deadline == second.deadline == 120.0
                assert second.remaining() == 5.0
            first.conn.close()
            second.conn.close()


def test_budget_resets_after_a_command_and_a_shorter_call_can_remain_shorter():
    with patch("time.monotonic", return_value=100.0):
        with timing.command("workflow run", 20):
            short = Client(5)
            assert short.deadline == 105.0
            short.conn.close()
        with patch("time.monotonic", return_value=115.0):
            fresh = Client(20)
            assert fresh.deadline == 135.0
            fresh.conn.close()


def test_observation_is_local_to_one_read_boundary_not_a_revision_cache():
    current = {"revision": "same", "density": 1}
    with patch.object(
        Client, "_exchange", side_effect=lambda *a, **k: {"ok": True, "data": dict(current)}
    ) as exchange:
        with Client() as client:
            with client.observation():
                first = client.op("model.show", {"model": "x.prt"})
                first["density"] = 99
                assert client.op("model.show", {"model": "x.prt"})["density"] == 1
            current["density"] = 2
            with client.observation():
                assert client.op("model.show", {"model": "x.prt"})["density"] == 2
            assert exchange.call_count == 2


def test_a_read_boundary_cannot_dispatch_a_write_and_never_caches_material_reads():
    with patch.object(Client, "_exchange", return_value={"ok": True, "data": {}}) as exchange:
        with Client() as client:
            with client.observation():
                client.op("material.list", {"model": "x.prt"})
                client.op("material.list", {"model": "x.prt"})
                with pytest.raises(Error) as error:
                    client.op("model.save", {"model": "x.prt"}, write=True)
                assert error.value.details["dispatch_state"] == "not_started"
            assert exchange.call_count == 2


class PropertyEvidenceReuse(building_fixture.Built):
    def test_material_refresh_precedes_shared_property_and_dependency_sample(self):
        from creo_cli import engine, workflow_properties

        self.block()
        self.world.events.clear()
        with patch.dict(os.environ, self.env), Client() as client:
            with client.observation():
                observed = workflow_properties.observe(client, {"block.prt"}, {"block.prt"})
                self.assertEqual(engine.show(client, "block.prt")["model"], "block.prt")
                self.assertEqual(observed["models"]["block.prt"]["model"]["model"], "block.prt")
            self.assertEqual(self.world.ops().count("model.show"), 1)
            self.assertLess(
                self.world.ops().index("material.list"), self.world.ops().index("model.show")
            )
            engine.show(client, "block.prt")
            self.assertEqual(self.world.ops().count("model.show"), 2)

    def test_receipt_uses_the_verified_solid_snapshot_without_an_extra_unverified_copy(self):
        model = self.block()
        name = next(d["name"] for d in model["dimensions"] if d["name"].startswith("d"))
        self.world.events.clear()
        data = self.gated(
            "dimension",
            "set-tolerance",
            "--model",
            "block.prt",
            "--dimension",
            name,
            "--symmetric",
            "0.1",
            "--units",
            "mm",
        )["data"]
        after_write = self.world.ops()[self.world.ops().index("dimension.tolerance") + 1 :]
        self.assertEqual(after_write.count("geometry.list"), 1)
        self.assertEqual(data["receipt"]["outcome"]["verification"]["status"], "passed")
