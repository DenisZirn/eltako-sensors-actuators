from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from collections.abc import Iterable
from typing import Protocol

import serialx

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
        self._serial: serialx.BaseSerial | None = None
        self._lock = threading.Lock()
        # serialx is based on RawIOBase: read(n) is allowed to return fewer
        # than n bytes. Keep an RX byte stream between gateway polls so no
        # radio telegram is lost when USB splits it across reads.
        self._rx_buffer = bytearray()

    def open(self) -> None:
        if self._serial is not None and self._serial.is_open:
            if self.is_active():
                return
            self.close()
        self._serial = serialx.serial_for_url(
            self.port,
            baudrate=self.baudrate,
            byte_size=8,
            parity=serialx.Parity.NONE,
            stopbits=serialx.StopBits.ONE,
            read_timeout=self.timeout,
            write_timeout=self.write_timeout,
        )
        self._serial.open()
        # A reopened port starts a fresh byte stream. Never splice a frame
        # from an old USB session together with frames from a new session.
        self._rx_buffer.clear()
        # serialx has no equivalent of pyserial's rs485.RS485Settings.
        # This implementation relies on USB-RS485 adapters handling direction
        # automatically. Verify FGW14-USB/FAM14 send and receive on real
        # hardware during hardware validation.
        if self.rs485_mode:
            _LOGGER.warning(
                "ELTAKO serialx: RS485 kernel mode not configured; "
                "verify hardware automatic direction control (port=%s)",
                self.port,
            )
        _LOGGER.info("ELTAKO serial transport opened: port=%s baudrate=%s rs485_mode=%s protocol=%s", self.port, self.baudrate, self.rs485_mode, self.protocol)

    def close(self) -> None:
        if self._serial is not None:
            try:
                if self._serial.is_open:
                    self._serial.close()
            finally:
                self._serial = None
                self._rx_buffer.clear()
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
            self._serial.reset_write_buffer()
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
            self._serial.reset_write_buffer()
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

    def _take_esp2_frame(self) -> bytes | None:
        """Extract one checksum-valid ESP2 frame from the persistent RX stream.

        All ESP2 radio variants share the same 14-byte framing, including RPS
        press/release, 1BS contacts, 4BS sensors and separate physical battery
        sender IDs. Invalid bytes are skipped one at a time, so valid frames
        after noise or a truncated frame can still be recovered.
        """
        pending = self._rx_buffer
        frame_size = 14

        while pending:
            start = pending.find(PREAMBLE)
            if start < 0:
                # Keep the first preamble byte if the next serial read starts
                # with its second byte (A5 | 5A).
                keep = 1 if pending[-1] == PREAMBLE[0] else 0
                discarded = len(pending) - keep
                if discarded:
                    del pending[:discarded]
                    _LOGGER.debug(
                        "ELTAKO ESP2 resynchronization: skipped %d noise byte(s) port=%s",
                        discarded, self.port,
                    )
                return None

            if start:
                del pending[:start]
                _LOGGER.debug(
                    "ELTAKO ESP2 resynchronization: skipped %d byte(s) port=%s",
                    start, self.port,
                )

            if len(pending) < frame_size:
                # Do not discard the partial frame on USB read timeout. The
                # rest may arrive on the next read_frame() call.
                return None

            candidate = bytes(pending[:frame_size])
            try:
                ESP2Message.parse(candidate)
            except ValueError as err:
                _LOGGER.debug(
                    "ELTAKO invalid ESP2 frame: port=%s error=%s candidate=%s",
                    self.port, err, candidate.hex("-"),
                )
                # Shift one byte, not fourteen: a valid preamble may start
                # inside a damaged frame or immediately afterwards.
                del pending[0]
                continue

            del pending[:frame_size]
            return candidate

        return None

    def read_frame(self) -> bytes | None:
        """Receive an entire ESP2 frame without losing fragmented USB reads.

        serialx.read() may return only the currently available bytes. Complete
        frames are buffered and delivered individually in arrival order. A
        short bounded readinto() coalesces USB fragments with low latency;
        incomplete frames remain buffered across polls and timeouts.
        """
        self.open()
        if self._serial is None:
            raise RuntimeError("Serial port is not open")
        if not self.is_active():
            raise RuntimeError(f"Serial port is not active: {self.port}")

        with self._lock:
            # Drain complete buffered frames first. In a USB burst this keeps
            # individual press/release and battery telegrams in FIFO order.
            frame = self._take_esp2_frame()
            if frame is None:
                chunk = self._serial.read(128)
                if chunk:
                    self._rx_buffer.extend(chunk)
                    frame = self._take_esp2_frame()

            if frame is None and self._rx_buffer:
                # A complete 14-byte frame takes ~15 ms at FAM-USB 9600 baud,
                # ~2.5 ms at FGW14-USB 57600 baud. Collect subsequent bytes
                # briefly so ordinary press/release events remain responsive.
                # This time is strictly bounded to avoid delaying concurrent
                # actuator sends on our shared RX/TX transport lock.
                coalesce_time = min(0.05, max(0.01, 350.0 / max(1, self.baudrate)))
                deadline = time.monotonic() + coalesce_time
                scratch = bytearray(128)
                while frame is None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    received = self._serial.readinto(scratch, timeout=remaining)
                    if not received:
                        break
                    self._rx_buffer.extend(scratch[:received])
                    frame = self._take_esp2_frame()

        if frame is not None:
            _LOGGER.debug(
                "ELTAKO serial frame received: port=%s frame=%s",
                self.port, frame.hex("-"),
            )
        return frame
