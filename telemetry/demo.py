"""Synthetic Monza-like session for UI demo without the game running."""

from __future__ import annotations

import math
import time
from typing import Any

# Simplified Monza outline in local XZ (normalized later by frontend)
MONZA_PATH: list[tuple[float, float]] = [
    (0.00, 0.00),
    (0.12, 0.02),
    (0.22, 0.08),
    (0.28, 0.18),  # Variante del Rettifilo
    (0.32, 0.28),
    (0.30, 0.40),
    (0.34, 0.52),
    (0.42, 0.58),
    (0.55, 0.60),
    (0.68, 0.55),
    (0.78, 0.42),  # Lesmo
    (0.82, 0.28),
    (0.80, 0.16),
    (0.72, 0.08),
    (0.62, 0.02),
    (0.52, -0.02),
    (0.42, -0.08),  # Ascari
    (0.35, -0.18),
    (0.38, -0.30),
    (0.48, -0.36),
    (0.62, -0.34),
    (0.74, -0.28),
    (0.82, -0.18),  # Parabolica
    (0.85, -0.06),
    (0.78, 0.02),
    (0.60, 0.04),
    (0.40, 0.03),
    (0.20, 0.01),
    (0.00, 0.00),
]

MONZA_CORNERS = [
    {"id": 1, "name": "Variante del Rettifilo", "start": 0.08, "end": 0.16},
    {"id": 2, "name": "Curva Grande", "start": 0.20, "end": 0.28},
    {"id": 3, "name": "Variante della Roggia", "start": 0.30, "end": 0.38},
    {"id": 4, "name": "Lesmo 1", "start": 0.42, "end": 0.48},
    {"id": 5, "name": "Lesmo 2", "start": 0.50, "end": 0.56},
    {"id": 6, "name": "Ascari", "start": 0.62, "end": 0.74},
    {"id": 7, "name": "Parabolica", "start": 0.82, "end": 0.95},
]


def _point_on_path(npos: float) -> tuple[float, float]:
    npos = npos % 1.0
    pts = MONZA_PATH
    # cumulative lengths
    lengths = [0.0]
    for i in range(1, len(pts)):
        x0, z0 = pts[i - 1]
        x1, z1 = pts[i]
        lengths.append(lengths[-1] + math.hypot(x1 - x0, z1 - z0))
    total = lengths[-1] or 1.0
    target = npos * total
    for i in range(1, len(pts)):
        if lengths[i] >= target:
            seg = lengths[i] - lengths[i - 1] or 1.0
            t = (target - lengths[i - 1]) / seg
            x = pts[i - 1][0] + (pts[i][0] - pts[i - 1][0]) * t
            z = pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * t
            return x * 1200.0, z * 1200.0
    return pts[-1][0] * 1200.0, pts[-1][1] * 1200.0


def _profile(npos: float, *, reference: bool) -> dict[str, float]:
    """Speed / inputs shaped around Monza corners; reference is cleaner & faster."""
    # base speed map
    speed = 290.0
    brake = 0.0
    gas = 1.0
    steer = 0.0

    corners = [
        (0.10, 0.14, 95, 0.85, -0.35),
        (0.32, 0.36, 110, 0.75, 0.40),
        (0.44, 0.47, 145, 0.55, -0.25),
        (0.51, 0.55, 130, 0.60, 0.30),
        (0.66, 0.72, 120, 0.70, -0.45),
        (0.86, 0.93, 160, 0.50, -0.55),
    ]
    for start, end, min_spd, peak_brake, peak_steer in corners:
        if start <= npos <= end:
            mid = (start + end) / 2
            w = 1.0 - abs(npos - mid) / ((end - start) / 2 + 1e-6)
            w = max(0.0, min(1.0, w))
            speed = min_spd + (290 - min_spd) * (1 - w * 0.85)
            brake = peak_brake * w
            gas = max(0.0, 1.0 - w * 1.2)
            steer = peak_steer * w
            break

    if not reference:
        # driver mistakes: late braking into chicane, early throttle Ascari, slow Parabolica
        if 0.09 <= npos <= 0.15:
            speed -= 12
            brake = min(1.0, brake + 0.15)
            gas *= 0.7
        if 0.66 <= npos <= 0.73:
            gas = min(1.0, gas + 0.35)
            steer *= 1.15
            speed -= 8
        if 0.86 <= npos <= 0.94:
            speed -= 18
            brake = min(1.0, brake + 0.1)
            gas *= 0.85

    slip = abs(steer) * 0.15 + brake * 0.05 + (0.12 if not reference and 0.66 <= npos <= 0.73 else 0.03)
    return {
        "speed": speed,
        "gas": max(0.0, min(1.0, gas)),
        "brake": max(0.0, min(1.0, brake)),
        "steer": steer,
        "slip": slip,
    }


def synthesize_lap(*, reference: bool, n: int = 360, lap_time_ms: int | None = None) -> list[dict[str, Any]]:
    if lap_time_ms is None:
        lap_time_ms = 105200 if reference else 107850
    samples: list[dict[str, Any]] = []
    for i in range(n):
        npos = i / n
        p = _profile(npos, reference=reference)
        x, z = _point_on_path(npos)
        # slight radial offset for "current" line to show trajectory difference
        if not reference:
            x += math.sin(npos * math.tau * 3) * 8
            z += math.cos(npos * math.tau * 2) * 6
        t_ms = int(lap_time_ms * npos)
        # accumulate time more where slower
        samples.append(
            {
                "t_ms": t_ms,
                "npos": npos,
                "speed": p["speed"],
                "gas": p["gas"],
                "brake": p["brake"],
                "steer": p["steer"],
                "rpm": 5500 + p["speed"] * 18,
                "gear": max(2, min(6, int(p["speed"] / 55))),
                "x": x,
                "y": 0.0,
                "z": z,
                "slip_fl": p["slip"] * 0.9,
                "slip_fr": p["slip"] * 1.0,
                "slip_rl": p["slip"] * 1.1,
                "slip_rr": p["slip"] * 1.15,
            }
        )
    # rebuild t_ms from speed integration for more realistic delta
    dist = 5793.0  # monza-ish meters
    ds = dist / n
    t = 0.0
    for s in samples:
        v = max(s["speed"], 30.0) / 3.6
        t += ds / v * 1000.0
        s["t_ms"] = int(t)
    return samples


class DemoPlayer:
    """Plays a synthetic session: map learns on lap 1, delta colours from lap 2 (like AC EVO)."""

    def __init__(self) -> None:
        from telemetry.track_map import TrackMapBuilder

        self.reference = synthesize_lap(reference=True)
        self.current = synthesize_lap(reference=False)
        self._i = 0
        self._lap = 1
        self.track = "monza"
        self.car = "Ferrari 296 GT3"
        self.started = time.time()
        self.mapper = TrackMapBuilder()
        self.electronics = {
            "electronics_tc_level": 3,
            "electronics_tc_level_max": 10,
            "electronics_abs_level": 2,
            "electronics_abs_level_max": 10,
            "electronics_brake_bias": 0.545,
            "electronics_diff_power": 40,
            "electronics_diff_coast": 30,
            "electronics_engine_map": 2,
            "electronics_front_bump_damper": 8,
            "electronics_front_rebound_damper": 10,
            "electronics_rear_bump_damper": 7,
            "electronics_rear_rebound_damper": 9,
        }

    def next_frame(self) -> dict[str, Any]:
        s = self.current[self._i]
        self._i = (self._i + 1) % len(self.current)
        if self._i == 0:
            self._lap += 1
        ref = self.reference[min(len(self.reference) - 1, int(s["npos"] * len(self.reference))) ]
        # AC EVO: delta vs best exists only after first completed lap
        delta = None
        best_ms = None
        if self._lap > 1 or self.mapper.laps_completed >= 1:
            delta = s["t_ms"] - ref["t_ms"]
            best_ms = self.reference[-1]["t_ms"]

        frame = {
            "mode": "demo",
            "connected": True,
            "track": self.track,
            "car": self.car,
            "lap": self._lap,
            "t_ms": s["t_ms"],
            "best_ms": best_ms,
            "npos": s["npos"],
            "speed": s["speed"],
            "gas": s["gas"],
            "brake": s["brake"],
            "steer": s["steer"],
            "rpm": s["rpm"],
            "gear": s["gear"],
            "x": s["x"],
            "y": s["y"],
            "z": s["z"],
            "delta_ms": delta,
            "slip": [s["slip_fl"], s["slip_fr"], s["slip_rl"], s["slip_rr"]],
            "electronics": self.electronics,
            "physics_setup": {
                "brake_bias": 0.545,
                "tyre_core_temp": [88.0, 89.0, 96.0, 97.0],
                "wheels_pressure": [27.2, 27.1, 26.8, 26.9],
            },
            "corners": MONZA_CORNERS,
            "ts": time.time(),
        }
        self.mapper.ingest(frame)
        snap = self.mapper.snapshot()
        # Until the outline is dense enough, keep a readable fallback outline
        if snap.get("coverage", 0) < 0.55 and snap.get("laps_completed", 0) < 1:
            snap = {
                **snap,
                "path": [
                    {"x": x * 1200.0, "z": z * 1200.0, "npos": i / (len(MONZA_PATH) - 1)}
                    for i, (x, z) in enumerate(MONZA_PATH)
                ],
                "map_ready": True,
                # sentinella: il tracciato di ripiego non e' quello del builder,
                # e va sostituito appena il vero path e' abbastanza denso
                "path_version": -1,
            }
        frame["map"] = snap
        return frame

    def demo_bundle(self) -> dict[str, Any]:
        return {
            "track": self.track,
            "car": self.car,
            "corners": MONZA_CORNERS,
            "path": [{"x": x * 1200.0, "z": z * 1200.0} for x, z in MONZA_PATH],
            "reference": self.reference,
            "current": self.current,
            "reference_lap_time_ms": self.reference[-1]["t_ms"],
            "current_lap_time_ms": self.current[-1]["t_ms"],
        }
