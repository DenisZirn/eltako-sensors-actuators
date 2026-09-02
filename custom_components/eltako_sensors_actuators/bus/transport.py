from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from collections.abc import Iterable
from typing import Protocol

import serial
from serial import rs485

from .esp2 import PREAMBLE, ESP2Message
from .esp3 import esp2_to_esp3_radio_erp1

_LOGGER = logging.getLogger(__name__)


class SerializableMessage(Protocol):
    def serialize(self) -> bytes: ...


class SerialTransport:
    """Small synchronous serial transport for ESP2 frames.

    Home Assistant calls this via async_add_executor_job from gateway.py so
    serial IO does not block the event loop.
    """

    def __init__(self, port: str, baudrate: int = 57600, timeout: float = 0.2, write_timeout: float = 1.0, delay: float = 0.05, rs485_mode: bool = False, protocol: str = "esp2") -> None:
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.write_timeout = write_timeout
        self.delay = delay
        self.rs485_mode = rs485_mode
        self.protocol = str(protocol or "esp2").lower()
        self._serial: serial.Serial | None = None
        self._lock = threading.Lock()

    def open(self) -> None:
        if self._serial is not None and self._serial.is_open:
            if self.is_active():
                return
            self.close()
        self._serial = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=self.timeout,
            write_timeout=self.write_timeout,
        )
        # FAM14/FGW14-USB can be half-duplex RS485 adapters. FAM-USB is a
        # wireless EnOcean USB gateway and must stay in normal serial mode.
        if self.rs485_mode:
            try:
                self._serial.rs485_mode = rs485.RS485Settings()
                _LOGGER.debug("ELTAKO serial transport RS485 mode enabled: port=%s", self.port)
            except Exception as err:
                _LOGGER.debug("ELTAKO serial transport RS485 mode not enabled: port=%s reason=%s", self.port, err)
        _LOGGER.info("ELTAKO serial transport opened: port=%s baudrate=%s rs485_mode=%s protocol=%s", self.port, self.baudrate, self.rs485_mode, self.protocol)

    def close(self) -> None:
        if self._serial is not None:
            try:
                if self._serial.is_open:
                    self._serial.close()
            finally:
                self._serial = None
                _LOGGER.info("ELTAKO serial transport closed: port=%s", self.port)

    def is_active(self) -> bool:
        if self._serial is None or not self._serial.is_open:
            return False
        try:
            if str(self.port).startswith("/dev/") and not Path(str(self.port)).exists():
                return False
        except Exception:
            pass
        return True

    def send(self, message: SerializableMessage | bytes | bytearray) -> bytes:
        self.open()
        if self._serial is None:
            raise RuntimeError("Serial port is not open")

        if self.protocol == "esp3":
            frame = esp2_to_esp3_radio_erp1(message)
        else:
            frame = bytes(message) if isinstance(message, (bytes, bytearray)) else message.serialize()
        with self._lock:
            self._serial.reset_output_buffer()
            written = self._serial.write(frame)
            self._serial.flush()
            if self.delay:
                time.sleep(self.delay)
        if written != len(frame):
            raise RuntimeError(f"Serial write incomplete: wrote {written}/{len(frame)} bytes")
        _LOGGER.info("ELTAKO serial frame sent: port=%s protocol=%s frame=%s", self.port, self.protocol, frame.hex("-"))
        return frame

    def send_many(
        self,
        messages: Iterable[SerializableMessage | bytes | bytearray],
        *,
        inter_frame_delay: float = 0.02,
    ) -> list[bytes]:
        """Send several frames as one uninterrupted serial burst.

        The reader and writer intentionally share one serial lock. Sending an
        RGBW component sequence through repeated ``send`` calls allows the
        reader to acquire that lock between frames and wait for the normal
        200 ms receive timeout. FRGBW14 then sees four separate operations
        instead of the compact controller burst emitted by GFA5.

        Convert all messages before taking the lock, then keep it for the
        complete sequence. This preserves frame order and prevents receive
        polling from stretching a roughly 100 ms RGBW burst to almost one
        second.
        """
        self.open()
        if self._serial is None:
            raise RuntimeError("Serial port is not open")

        frames = [
            esp2_to_esp3_radio_erp1(message)
            if self.protocol == "esp3"
            else (bytes(message) if isinstance(message, (bytes, bytearray)) else message.serialize())
            for message in messages
        ]
        if not frames:
            return []

        delay = max(0.0, float(inter_frame_delay))
        with self._lock:
            self._serial.reset_output_buffer()
            for index, frame in enumerate(frames):
                written = self._serial.write(frame)
                self._serial.flush()
                if written != len(frame):
                    raise RuntimeError(
                        f"Serial write incomplete: wrote {written}/{len(frame)} bytes"
                    )
                if delay and index < len(frames) - 1:
                    time.sleep(delay)

        _LOGGER.info(
            "ELTAKO serial frame burst sent: port=%s protocol=%s frames=%s delay=%.3fs",
            self.port,
            self.protocol,
            [frame.hex("-") for frame in frames],
            delay,
        )
        return frames

    def read_frame(self) -> bytes | None:
        """Read one ESP2 frame if available, else return None.

        This function synchronizes on the A5 5A preamble and then reads the
        remaining 12 bytes. It is intentionally small and strict; invalid frames
        are logged at debug level and discarded by the caller.
        """
        self.open()
        if self._serial is None:
            raise RuntimeError("Serial port is not open")
        if not self.is_active():
            raise RuntimeError(f"Serial port is not active: {self.port}")

        with self._lock:
            first = self._serial.read(1)
            if not first:
                return None
            if first != PREAMBLE[:1]:
                return None
            second = self._serial.read(1)
            if second != PREAMBLE[1:2]:
                return None
            rest = self._serial.read(12)
            if len(rest) != 12:
                return None
            frame = PREAMBLE + rest

        # Validate before returning so gateway only handles valid frames.
        ESP2Message.parse(frame)
        _LOGGER.debug("ELTAKO serial frame received: port=%s frame=%s", self.port, frame.hex("-"))
        return frame
