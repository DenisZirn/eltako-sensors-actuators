from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "custom_components" / "eltako_sensors_actuators" / "manager_importers.py"
SPEC = importlib.util.spec_from_file_location("manager_importers", MODULE)
assert SPEC and SPEC.loader
manager_importers = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manager_importers)


CATALOG = {
    "devices": [
        {
            "key": "M5-38-08-FMS14",
            "eep_out": "M5-38-08",
            "platform": "light",
            "device_type": "FMS14",
            "eltako": "FMS14",
            "needs_sender": True,
            "sender_eep": "A5-38-08",
        },
        {
            "key": "F6-02-01-F2L14",
            "eep_out": "F6-02-01",
            "platform": "fan",
            "device_type": "F2L14",
            "eltako": "F2L14",
            "needs_sender": True,
            "sender_eep": "F6-02-01",
        },
        {
            "key": "F6-02-01-4CH",
            "eep_out": "F6-02-01",
            "platform": "binary_sensor",
            "device_type": "FT55",
            "eltako": "FT55, F4T55E 4-Kanal",
        },
        {
            "key": "M5-38-08-FSR61-230V",
            "eep_out": "M5-38-08",
            "platform": "light",
            "device_type": "FSR61-230V",
            "eltako": "FSR61-230V",
            "needs_sender": True,
            "sender_eep": "A5-38-08",
        },
    ]
}


class ManagerImporterTests(unittest.TestCase):
    def test_pct14_fms14_two_channels(self) -> None:
        xml = """<?xml version="1.0"?>
<exchange>
  <rootdevice><rootdevicedata><baseid>
    <baseid_byte_0>255</baseid_byte_0><baseid_byte_1>170</baseid_byte_1>
    <baseid_byte_2>0</baseid_byte_2><baseid_byte_3>0</baseid_byte_3>
  </baseid></rootdevicedata></rootdevice>
  <devices>
    <device><name>FMS14</name><header><address>10</address><addressrange>1</addressrange></header></device>
  </devices>
</exchange>"""
        result = manager_importers.parse_pct14_xml(xml, CATALOG)
        self.assertEqual(result["base_id"], "FF-AA-00-00")
        self.assertEqual(len(result["rows"]), 2)
        self.assertEqual(result["rows"][0]["id"], "00-00-00-0A")
        self.assertEqual(result["rows"][1]["id"], "00-00-00-0B")
        self.assertEqual(result["rows"][0]["sender_id"], "00-00-B0-0A")
        self.assertEqual(result["rows"][0]["profile_key"], "M5-38-08-FMS14")

    def test_pct14_f2l14_is_one_logical_device(self) -> None:
        xml = """<exchange><devices><device><name>F2L14</name>
<header><address>60</address><addressrange>2</addressrange></header>
<rangeofid><entry><entry_function>56</entry_function><entry_button>7</entry_button>
<entry_channel>3</entry_channel><entry_value>1</entry_value></entry></rangeofid>
</device></devices></exchange>"""
        result = manager_importers.parse_pct14_xml(xml, CATALOG)
        self.assertEqual(len(result["rows"]), 1)
        row = result["rows"][0]
        self.assertEqual(row["stage_1_id"], "00-00-00-3C")
        self.assertEqual(row["stage_2_id"], "00-00-00-3D")
        self.assertEqual(row["f2l14_mode"], "additive")

    def test_minisafe_rooms_and_sender_id(self) -> None:
        config = {
            "system": {
                "rooms": [{"index": 3, "name": "Keller"}],
                "devices": [{
                    "name": "Taster Keller",
                    "room": 3,
                    "info": {
                        "type": "ENOCEAN",
                        "vendor": "Eltako",
                        "address": "AABBCC01",
                        "deviceText": "FT55",
                        "sid": "1",
                    },
                }],
            }
        }
        states = [{
            "type": "ENOCEAN",
            "sid": "1",
            "adr": "AABBCC01",
            "senderID": "FF010203",
        }]
        text = json.dumps(config) + "\n192.0.2.1: /getStates\n" + json.dumps(states)
        result = manager_importers.parse_minisafe2(text, CATALOG)
        self.assertEqual(len(result["rows"]), 1)
        row = result["rows"][0]
        self.assertEqual(row["id"], "AA-BB-CC-01")
        self.assertEqual(row["area"], "Keller")
        self.assertEqual(row["sender_id"], "FF-01-02-03")
        self.assertEqual(row["profile_key"], "F6-02-01-4CH")

    def test_format_detection(self) -> None:
        self.assertEqual(manager_importers.detect_import_format("<exchange/>", "project.xml"), "pct14")
        self.assertEqual(manager_importers.detect_import_format("eltako:\n  gateway: []", "x.yaml"), "eedtoy_yaml")
        self.assertEqual(
            manager_importers.detect_import_format('{"system":{"devices":[{"info":{"vendor":"eltako"}}]}}', "x.json"),
            "minisafe2",
        )


if __name__ == "__main__":
    unittest.main()
