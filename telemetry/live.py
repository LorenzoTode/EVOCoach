"""Read AC EVO named shared memory via acevo-sdk, with retry and reconnect.

Uses RegionReader + decode_* rather than TelemetryCapture. TelemetryCapture is
built for a single recording session: it buffers every frame in memory and
stops the loop after heartbeat/disconnect timeouts. A live monitor needs to
wait for the game, survive a quit, and attach again when it restarts.
"""

from __future__ import annotations

import sys
import time
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any

from acevo import RegionReader, decode_graphics, decode_physics, decode_static

# Region names and map sizes come from acevo.capture.REGIONS (acevo-sdk 0.1.1).
# RegionReader prepends Local\ / Global\ itself — pass the bare mapping name.
PHYSICS_REGION = ("acevo_pmf_physics", 1024)
GRAPHICS_REGION = ("acevo_pmf_graphics", 4096)
STATIC_REGION = ("acevo_pmf_static", 2048)

# Graphics distance/progress: native Evo field is current_km; the decoder also
# documents a legacy alias normalized_car_position on the graphics payload.
GRAPHICS_PRINT_KEYS = (
    "current_km",
    "normalized_car_position",
    "current_lap_time_ms",
    "session_current_lap",
    "car_model",
    "track",
)


def _as_dict(payload: Any) -> dict[str, Any]:
    if payload is None:
        return {}
    if isinstance(payload, dict):
        return payload
    if is_dataclass(payload):
        return asdict(payload)
    return {}


def _fmt_num(value: Any, digits: int = 2) -> str:
    if isinstance(value, bool) or value is None:
        return "n/a"
    if isinstance(value, (int, float)):
        if isinstance(value, float):
            return f"{value:.{digits}f}"
        return str(value)
    return "n/a"


def _fmt_slip(values: Any) -> str:
    """Format a 4-wheel list. acevo-sdk stores unnamed floats (FL, FR, RL, RR in the AC/ACC layout)."""
    if not isinstance(values, list) or len(values) != 4:
        return "n/a"
    parts = []
    for item in values:
        parts.append(_fmt_num(item, 3) if item is not None else "n/a")
    return "[" + " ".join(parts) + "]"


@dataclass
class SharedMemorySnapshot:
    """One poll of decoded physics/graphics/static dicts from acevo-sdk."""

    physics: dict[str, Any]
    graphics: dict[str, Any]
    static: dict[str, Any]


class LiveSharedMemoryClient:
    """Open, poll, and reconnect the three AC EVO shared-memory regions."""

    def __init__(self, retry_seconds: float = 1.0) -> None:
        if sys.platform != "win32":
            raise RuntimeError("AC EVO shared memory is Windows-only (Win32 file mappings).")
        self.retry_seconds = retry_seconds
        self._readers: dict[str, RegionReader] = {}
        self._logged_waiting = False
        self._logged_graphics_keys = False

    @property
    def connected(self) -> bool:
        return "physics" in self._readers

    def close(self) -> None:
        for reader in self._readers.values():
            try:
                reader.close()
            except Exception:
                pass
        self._readers = {}

    def ensure_connected(self) -> bool:
        """Try to open missing regions. Returns True once physics is available."""
        for key, spec in (
            ("physics", PHYSICS_REGION),
            ("graphics", GRAPHICS_REGION),
            ("static", STATIC_REGION),
        ):
            if key in self._readers:
                continue
            name, size = spec
            reader = RegionReader(name, size)
            try:
                if reader.open():
                    self._readers[key] = reader
            except OSError:
                try:
                    reader.close()
                except Exception:
                    pass

        if self.connected:
            if self._logged_waiting:
                regions = ",".join(sorted(self._readers))
                print(f"\nConnected to shared memory ({regions}).", flush=True)
                self._logged_waiting = False
            return True

        if not self._logged_waiting:
            print(
                "Waiting for AC EVO shared memory "
                "(start the game and enter a session)...",
                flush=True,
            )
            self._logged_waiting = True
        return False

    def _drop_reader(self, key: str) -> None:
        reader = self._readers.pop(key, None)
        if reader is None:
            return
        try:
            reader.close()
        except Exception:
            pass

    def _read_region(self, key: str, decoder) -> dict[str, Any]:
        reader = self._readers.get(key)
        if reader is None:
            return {}
        try:
            raw = reader.read_raw()
        except (OSError, RuntimeError):
            self._drop_reader(key)
            return {}
        try:
            return _as_dict(decoder(raw))
        except Exception as exc:
            return {"error": str(exc)}

    def poll(self) -> SharedMemorySnapshot | None:
        """Read one frame. Returns None if physics is not connected."""
        if not self.ensure_connected():
            return None

        physics = self._read_region("physics", decode_physics)
        if not physics or physics.get("error"):
            self._drop_reader("physics")
            print("\nLost physics shared memory — will retry.", flush=True)
            return None

        graphics = self._read_region("graphics", decode_graphics)
        static = self._read_region("static", decode_static)

        if graphics and not graphics.get("error") and not self._logged_graphics_keys:
            missing = [k for k in GRAPHICS_PRINT_KEYS if k not in graphics]
            if missing:
                known = ", ".join(sorted(graphics.keys())[:40])
                print(
                    f"\nNote: graphics keys not present ({', '.join(missing)}). "
                    f"Available keys include: {known}",
                    flush=True,
                )
            self._logged_graphics_keys = True

        return SharedMemorySnapshot(physics=physics, graphics=graphics, static=static)

    def format_line(self, snapshot: SharedMemorySnapshot) -> str:
        p = snapshot.physics
        g = snapshot.graphics
        s = snapshot.static

        speed = _fmt_num(p.get("speed_kmh"), 1)
        gas = _fmt_num(p.get("gas"), 2)
        brake = _fmt_num(p.get("brake"), 2)
        steer = _fmt_num(p.get("steer_angle"), 3)
        rpm = _fmt_num(p.get("rpms"), 0)
        gear = _fmt_num(p.get("gear"), 0)
        packet = _fmt_num(p.get("packet_id"), 0)
        slip = _fmt_slip(p.get("wheel_slip"))
        slip_ratio = _fmt_slip(p.get("slip_ratio"))

        # Distance: graphics.current_km is decoded from SPageFileGraphicEvo.
        # Physics.normalized_car_position in acevo-sdk is an estimate from tyre
        # contact Z and is marked non-authoritative — prefer graphics.
        current_km = g.get("current_km")
        npos = g.get("normalized_car_position")
        if npos is None:
            npos = p.get("normalized_car_position")
        lap_ms = g.get("current_lap_time_ms")
        lap_no = g.get("session_current_lap")
        car = g.get("car_model") or "n/a"
        track = s.get("track") or g.get("track") or "n/a"

        return (
            f"pkt={packet}  "
            f"{speed} km/h  "
            f"gas={gas}  brk={brake}  str={steer}  "
            f"rpm={rpm}  gear={gear}  "
            f"slip={slip}  ratio={slip_ratio}  "
            f"km={_fmt_num(current_km, 3)}  "
            f"npos={_fmt_num(npos, 3)}  "
            f"lap={_fmt_num(lap_no, 0)}  "
            f"t={_fmt_num(lap_ms, 0)}ms  "
            f"{track} / {car}"
        )

    def run_forever(self, hz: float = 10.0) -> None:
        interval = 1.0 / max(hz, 0.5)
        print(f"Polling at {hz:.1f} Hz. Ctrl+C to stop.", flush=True)
        try:
            while True:
                started = time.perf_counter()
                snapshot = self.poll()
                if snapshot is None:
                    time.sleep(self.retry_seconds)
                    continue
                print("\r" + self.format_line(snapshot) + "    ", end="", flush=True)
                elapsed = time.perf_counter() - started
                remaining = interval - elapsed
                if remaining > 0:
                    time.sleep(remaining)
        except KeyboardInterrupt:
            print("\nStopped.", flush=True)
        finally:
            self.close()
