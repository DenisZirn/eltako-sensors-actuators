from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "custom_components" / "eltako_sensors_actuators" / "series14_writer.py"
SPEC = importlib.util.spec_from_file_location("series14_writer", MODULE)
assert SPEC and SPEC.loader
series14_writer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(series14_writer)


class Series14WriterTests(unittest.TestCase):
    def test_build_sender_map_deduplicates(self) -> None:
        entries = [
            {
                "device_id": "FF-AA-00-08",
                "sender_id": "00-00-B0-08",
                "sender_eep": "A5-38-08",
                "device_type": "FUD14",
            },
            {
                "device_id": "FF-AA-00-08",
                "sender_id": "00-00-B0-08",
                "sender_eep": "A5-38-08",
                "device_type": "FUD14",
            },
        ]
        result = series14_writer.build_sender_map(entries)
        self.assertEqual(list(result), ["FF-AA-00-08"])
        self.assertEqual(len(result["FF-AA-00-08"]), 1)

    def test_target_bus_addresses_from_fam14_base(self) -> None:
        sender_map = series14_writer.build_sender_map([
            {
                "device_id": "FF-AA-00-08",
                "sender_id": "00-00-B0-08",
                "sender_eep": "A5-38-08",
            },
            {
                "device_id": "FF-AA-00-10",
                "sender_id": "00-00-B0-10",
                "sender_eep": "A5-38-08",
            },
        ])
        self.assertEqual(
            series14_writer.target_bus_addresses(0xFFAA0000, sender_map),
            [8, 16],
        )

    def test_norm_id(self) -> None:
        self.assertEqual(series14_writer.norm_id("ff:aa:00:08"), "FF-AA-00-08")


if __name__ == "__main__":
    unittest.main()
