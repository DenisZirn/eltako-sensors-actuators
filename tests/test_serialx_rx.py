"""Regression tests for fragmented ESP2 receive and independent sender IDs."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "eltako_sensors_actuators"
PKG = "eltako_rx_release_test"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


for name, path in ((PKG, INTEGRATION), (f"{PKG}.bus", INTEGRATION / "bus")):
    mod = types.ModuleType(name)
    mod.__path__ = [str(path)]
    sys.modules[name] = mod

# No serial adapter or Home Assistant runtime is required for these tests.
serialx = types.ModuleType("serialx")
serialx.BaseSerial = object
serialx.Parity = types.SimpleNamespace(NONE="N")
serialx.StopBits = types.SimpleNamespace(ONE=1)
sys.modules["serialx"] = serialx

esp2 = load(f"{PKG}.bus.esp2", INTEGRATION / "bus" / "esp2.py")
load(f"{PKG}.bus.esp3", INTEGRATION / "bus" / "esp3.py")
transport_mod = load(f"{PKG}.bus.transport", INTEGRATION / "bus" / "transport.py")


class FakeSerial:
    def __init__(self, fragments: list[bytes]):
        self.fragments = [bytearray(f) for f in fragments]
        self.is_open = True

    def read(self, n: int) -> bytes:
        if not self.fragments:
            return b""
        return bytes(self._take(n))

    def readinto(self, buffer: bytearray, *, timeout=None) -> int:
        data = self._take(len(buffer))
        buffer[: len(data)] = data
        return len(data)

    def _take(self, n: int) -> bytes:
        if not self.fragments:
            return b""
        chunk = self.fragments[0]
        result = bytes(chunk[:n])
        del chunk[:n]
        if not chunk:
            self.fragments.pop(0)
        return result


class ReceiveRegressionTests(unittest.TestCase):
    def transport(self, chunks: list[bytes]):
        instance = transport_mod.SerialTransport("virtual", baudrate=9600)
        instance._serial = FakeSerial(chunks)
        return instance

    def test_ft55_press_release_split_across_read_calls(self):
        press = esp2.build_rps(b"\x01\x02\x03\x04", 0x70, outgoing=False).serialize()
        release = esp2.build_rps(b"\x01\x02\x03\x04", 0x00, outgoing=False).serialize()
        t = self.transport([press[:1], press[1:4], press[4:9], press[9:] + release[:6], release[6:]])
        received = [frame for _ in range(15) if (frame := t.read_frame()) is not None]
        self.assertEqual(received, [press, release])

    def test_battery_unique_id_not_merged_with_channel_ids(self):
        # F4USM61B channel IDs and its physical battery sender ID are distinct.
        battery = esp2.build_regular_4bs(b"\xFF\xD8\x9D\x03", b"\x01\x02\x03\x04", outgoing=False).serialize()
        channel_a = esp2.build_regular_4bs(b"\xFF\xD8\x9D\x04", b"\x00\x00\x0A\x09", outgoing=False).serialize()
        channel_b = esp2.build_regular_4bs(b"\xFF\xD8\x9D\x05", b"\x00\x00\xEB\x09", outgoing=False).serialize()
        stream = battery + channel_a + channel_b
        t = self.transport([stream[:7], stream[7:24], stream[24:38], stream[38:]])
        received = [frame for _ in range(16) if (frame := t.read_frame()) is not None]
        self.assertEqual(received, [battery, channel_a, channel_b])

    def test_corrupt_frame_does_not_discard_later_valid_frame(self):
        good = esp2.build_rps(b"\x01\x02\x03\x04", 0x70, outgoing=False).serialize()
        corrupt = bytearray(good)
        corrupt[-1] ^= 0xFF
        t = self.transport([b"\x99\x98" + bytes(corrupt) + good[:5], good[5:]])
        received = [frame for _ in range(12) if (frame := t.read_frame()) is not None]
        self.assertEqual(received, [good])

    def test_partial_preamble_survives_timeout(self):
        frame = esp2.build_rps(b"\x01\x02\x03\x04", 0x70, outgoing=False).serialize()
        t = self.transport([frame[:1]])
        self.assertIsNone(t.read_frame())
        self.assertEqual(t._rx_buffer, bytearray(frame[:1]))
        t._serial.fragments.append(bytearray(frame[1:]))
        self.assertEqual(t.read_frame(), frame)


if __name__ == "__main__":
    unittest.main()
