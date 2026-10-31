"""An old rounding service cannot enter the new diagonal-explosion precision route."""

from tests.test_commands import Base
from tests.test_round7_closeout import invoke


class GeometryPrecisionCapability(Base):
    def test_old_explosion_cap_without_binary64_cap_refuses_preview_before_cad_dispatch(self):
        self.part("owned.asm")
        self.world.capabilities["explosion_state_readback"] = 2
        self.world.capabilities["assembly_explosion_context_readback"] = 1
        self.world.capabilities.pop("geometry_binary64_readback", None)
        request = self.request(
            {
                "units": "mm",
                "name": "DIAGONAL",
                "moves": [
                    {
                        "components": ["40"],
                        "direction": [1, 1, 1],
                        "distance": 123.456789012345,
                    }
                ],
            }
        )
        self.world.events.clear()
        code, answer = invoke(
            self,
            "assembly",
            "explode",
            "apply",
            "--model",
            "owned.asm",
            "--request",
            request,
            "--dry-run",
        )
        self.assertNotEqual(code, 0)
        self.assertFalse(answer["ok"])
        self.assertEqual(answer["error"]["code"], "E_BACKEND_UNAVAILABLE")
        details = answer["error"]["details"]
        self.assertEqual(
            details["required_capability"], {"name": "geometry_binary64_readback", "version": 1}
        )
        self.assertIsNone(details["observed_capability_version"])
        self.assertEqual(details["dispatch_state"], "not_started")
        self.assertFalse(details["request_sent"])
        self.assertEqual(self.world.events, [])
