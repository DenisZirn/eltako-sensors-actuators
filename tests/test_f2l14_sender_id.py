"""Regression checks for F2L14 controller transmit IDs vs actuator feedback IDs."""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "eltako_sensors_actuators"
PKG = "eltako_f2l14_sender_test"
for name, location in ((PKG, ROOT), (f"{PKG}.bus", ROOT / "bus")):
    mod = types.ModuleType(name)
    mod.__path__ = [str(location)]
    sys.modules[name] = mod

def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

load(f"{PKG}.bus.exceptions", ROOT / "bus" / "exceptions.py")
ids = load(f"{PKG}.bus.ids", ROOT / "bus" / "ids.py")
p = ROOT / "gateway.py"
tree = ast.parse(p.read_text(encoding="utf-8"))
functions = {"_is_f2l14_device", "_fam_usb_effective_sender_id", "_series14_pct_offset_from_device",
             "_fam_usb_effective_sender_id_for_device", "_effective_sender_id_for_gateway"}
parts = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in functions]
assert len(parts) == len(functions)
ns = {"parse_address": ids.parse_address, "format_address": ids.format_address,
      "GATEWAY_TYPE_FAM_USB": "fam-usb", "_is_frgbw14_device_config": lambda device: False}
exec(compile(ast.fix_missing_locations(ast.Module(body=parts, type_ignores=[])), str(p), "exec"), ns)

class F2L14SenderTests(unittest.TestCase):
    def setUp(self):
        self.device = {"platform": "fan", "device_type": "F2L14", "id": "FF-BF-5C-BC",
                       "sender_id": "FF-A6-04-BC", "stage_1_id": "FF-BF-5C-BC",
                       "stage_2_id": "FF-BF-5C-BD"}

    def sender(self, sender_id, gateway, base, device=None):
        return ns["_effective_sender_id_for_gateway"](sender_id, gateway, base, device or self.device)

    def test_f2l14_uses_learned_sender_not_status_id(self):
        sender = self.sender("FF-A6-04-BC", "fam-usb", "FF-A6-04-80")
        self.assertEqual(sender, "FF-A6-04-BC")
        self.assertNotIn(sender, (self.device["stage_1_id"], self.device["stage_2_id"]))

    def test_f2l14_maps_logical_sender_into_fam_usb_range(self):
        self.assertEqual(self.sender("00-00-B0-BC", "fam-usb", "FF-A6-04-80"), "FF-A6-04-BC")

    def test_non_f2l14_keeps_existing_mapping(self):
        self.assertEqual(self.sender("00-00-B0-07", "fam-usb", "FF-A6-04-80",
                                     {"platform": "switch", "device_type": "FSR14"}), "FF-A6-04-07")

    def test_bus_path_does_not_remap(self):
        self.assertEqual(self.sender("00-00-B0-BC", "fgw14usb", "FF-BF-5C-80"), "00-00-B0-BC")

    def test_feedback_addresses_unchanged(self):
        previous = dict(self.device)
        self.sender("FF-A6-04-BC", "fam-usb", "FF-A6-04-80")
        self.assertEqual(self.device, previous)

if __name__ == "__main__":
    unittest.main()
