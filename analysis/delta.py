"""Distance-aligned lap comparison and coaching insight extraction."""

from __future__ import annotations

from typing import Any

import numpy as np


def _series(samples: list[dict[str, Any]], key: str) -> tuple[np.ndarray, np.ndarray]:
    xs: list[float] = []
    ys: list[float] = []
    for s in samples:
        npos = s.get("npos")
        val = s.get(key)
        if npos is None or val is None:
            continue
        xs.append(float(npos))
        ys.append(float(val))
    if not xs:
        return np.array([]), np.array([])
    order = np.argsort(xs)
    return np.asarray(xs)[order], np.asarray(ys)[order]


def resample_to_grid(
    samples: list[dict[str, Any]],
    keys: list[str],
    grid: np.ndarray | None = None,
    n: int = 400,
) -> dict[str, np.ndarray]:
    """Align a lap onto a fixed normalized-position grid."""
    if grid is None:
        grid = np.linspace(0.0, 1.0, n, endpoint=False)
    out: dict[str, np.ndarray] = {"npos": grid}
    for key in keys:
        xs, ys = _series(samples, key)
        if len(xs) < 2:
            out[key] = np.full_like(grid, np.nan, dtype=float)
            continue
        # Unwrap duplicate npos by keeping last occurrence via interpolation-friendly unique
        uniq_x, uniq_idx = np.unique(xs, return_index=True)
        uniq_y = ys[uniq_idx]
        if len(uniq_x) < 2:
            out[key] = np.full_like(grid, np.nan, dtype=float)
            continue
        out[key] = np.interp(grid, uniq_x, uniq_y, left=uniq_y[0], right=uniq_y[-1])
    return out


def compute_delta(
    current: list[dict[str, Any]],
    reference: list[dict[str, Any]],
    n: int = 400,
) -> dict[str, Any]:
    """Compare current vs reference by distance; positive delta = behind (slower)."""
    keys = ["t_ms", "speed", "gas", "brake", "steer", "x", "y", "z"]
    grid = np.linspace(0.0, 1.0, n, endpoint=False)
    cur = resample_to_grid(current, keys, grid=grid)
    ref = resample_to_grid(reference, keys, grid=grid)

    t_cur = cur["t_ms"]
    t_ref = ref["t_ms"]
    delta_ms = t_cur - t_ref

    # instantaneous gain/loss along the lap (derivative of cumulative delta)
    instant = np.gradient(delta_ms) * n

    segments = []
    for i in range(n):
        d = float(delta_ms[i]) if np.isfinite(delta_ms[i]) else 0.0
        segments.append(
            {
                "npos": float(grid[i]),
                "delta_ms": d,
                "instant_ms": float(instant[i]) if np.isfinite(instant[i]) else 0.0,
                "speed": float(cur["speed"][i]) if np.isfinite(cur["speed"][i]) else None,
                "speed_ref": float(ref["speed"][i]) if np.isfinite(ref["speed"][i]) else None,
                "gas": float(cur["gas"][i]) if np.isfinite(cur["gas"][i]) else None,
                "brake": float(cur["brake"][i]) if np.isfinite(cur["brake"][i]) else None,
                "x": float(cur["x"][i]) if np.isfinite(cur["x"][i]) else None,
                "z": float(cur["z"][i]) if np.isfinite(cur["z"][i]) else None,
            }
        )

    final = float(delta_ms[-1]) if np.isfinite(delta_ms[-1]) else 0.0
    return {
        "n": n,
        "final_delta_ms": final,
        "segments": segments,
        "current_grid": {k: cur[k].tolist() for k in cur},
        "reference_grid": {k: ref[k].tolist() for k in ref},
    }


def corner_losses(
    delta: dict[str, Any],
    corners: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Rank corners by time lost vs reference."""
    segs = delta["segments"]
    results = []
    for corner in corners:
        start = float(corner["start"])
        end = float(corner["end"])
        window = [s for s in segs if start <= s["npos"] <= end]
        if len(window) < 2:
            continue
        loss = window[-1]["delta_ms"] - window[0]["delta_ms"]
        speed_gap = 0.0
        pairs = [
            (s["speed"], s["speed_ref"])
            for s in window
            if s["speed"] is not None and s["speed_ref"] is not None
        ]
        if pairs:
            speed_gap = float(np.mean([a - b for a, b in pairs]))
        results.append(
            {
                "id": corner.get("id"),
                "name": corner.get("name", f"Corner {corner.get('id')}"),
                "start": start,
                "end": end,
                "loss_ms": loss,
                "speed_gap_kmh": speed_gap,
                "mid_npos": (start + end) / 2.0,
            }
        )
    results.sort(key=lambda c: c["loss_ms"], reverse=True)
    return results


def driving_signals(samples: list[dict[str, Any]], corners: list[dict[str, Any]]) -> dict[str, Any]:
    """Heuristic signals used by the coach (trail-braking, early throttle, slip)."""
    if len(samples) < 10:
        return {"notes": [], "metrics": {}}

    grid = resample_to_grid(
        samples,
        ["speed", "gas", "brake", "steer", "slip_fl", "slip_fr", "slip_rl", "slip_rr"],
        n=300,
    )

    brake = grid["brake"]
    gas = grid["gas"]
    speed = grid["speed"]
    npos = grid["npos"]

    overlap = np.logical_and(brake > 0.15, gas > 0.15)
    coasting = np.logical_and(brake < 0.05, gas < 0.08, speed > 80)

    slip_vals = []
    for key in ("slip_fl", "slip_fr", "slip_rl", "slip_rr"):
        arr = grid[key]
        slip_vals.extend([float(v) for v in arr if np.isfinite(v)])
    avg_slip = float(np.mean(slip_vals)) if slip_vals else 0.0
    max_slip = float(np.max(slip_vals)) if slip_vals else 0.0

    notes: list[dict[str, Any]] = []
    if float(np.mean(overlap)) > 0.04:
        notes.append(
            {
                "severity": "medium",
                "topic": "inputs",
                "title": "Gas e freno insieme",
                "detail": "Troppo overlap gas/freno: stai combattendo te stesso in ingresso curva.",
            }
        )
    if float(np.mean(coasting)) > 0.08:
        notes.append(
            {
                "severity": "medium",
                "topic": "throttle",
                "title": "Coasting eccessivo",
                "detail": "Hai tratti lunghi senza gas né freno — porta più velocità o frena più tardi.",
            }
        )
    if max_slip > 0.35:
        notes.append(
            {
                "severity": "high",
                "topic": "grip",
                "title": "Slip elevato",
                "detail": f"Picco slip {max_slip:.2f}: probabilmente overdrive in uscita o bloccaggio in staccata.",
            }
        )

    # Early throttle proxy: first gas rise after brake peak in each corner
    for corner in corners[:8]:
        mask = (npos >= corner["start"]) & (npos <= corner["end"])
        if not np.any(mask):
            continue
        b = brake[mask]
        g = gas[mask]
        if len(b) < 4:
            continue
        peak_i = int(np.argmax(b))
        after = g[peak_i:]
        if len(after) and float(np.max(after)) > 0.6 and peak_i < len(b) * 0.35:
            notes.append(
                {
                    "severity": "low",
                    "topic": "exit",
                    "title": f"Uscita aggressiva — {corner.get('name')}",
                    "detail": "Gas molto presto dopo il picco freno: rischio understeer o rotazione incompleta.",
                }
            )

    return {
        "notes": notes[:12],
        "metrics": {
            "overlap_pct": round(float(np.mean(overlap)) * 100, 1),
            "coast_pct": round(float(np.mean(coasting)) * 100, 1),
            "avg_slip": round(avg_slip, 3),
            "max_slip": round(max_slip, 3),
            "avg_speed": round(float(np.nanmean(speed)), 1),
        },
    }


def build_analysis_payload(
    current_samples: list[dict[str, Any]],
    reference_samples: list[dict[str, Any]],
    corners: list[dict[str, Any]],
    meta: dict[str, Any] | None = None,
    *,
    electronics: dict[str, Any] | None = None,
    physics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from analysis.setup_acevo import build_acevo_setup_instructions

    delta = compute_delta(current_samples, reference_samples)
    ranked = corner_losses(delta, corners)
    driving = driving_signals(current_samples, corners)
    setup = build_acevo_setup_instructions(
        electronics=electronics,
        physics=physics,
        corner_rank=ranked,
        metrics=driving["metrics"],
    )

    trajectory_tips = []
    for c in ranked[:5]:
        if c["loss_ms"] < 40:
            continue
        direction = "più largo" if c["speed_gap_kmh"] > -2 else "più interno / cordolo"
        trajectory_tips.append(
            {
                "severity": "high" if c["loss_ms"] > 120 else "medium",
                "corner": c["name"],
                "loss_ms": round(c["loss_ms"], 0),
                "title": f"Perdi {c['loss_ms']:.0f} ms — {c['name']}",
                "detail": (
                    f"Rispetto al riferimento sei ~{abs(c['speed_gap_kmh']):.1f} km/h "
                    f"{'più lento' if c['speed_gap_kmh'] < 0 else 'più veloce'} nel tratto. "
                    f"Prova linea {direction} e confronta il punto di corda."
                ),
                "npos": c["mid_npos"],
            }
        )

    return {
        "meta": meta or {},
        "delta": {
            "final_delta_ms": delta["final_delta_ms"],
            "segments": delta["segments"],
        },
        "corners": ranked,
        "setup": setup,
        "trajectory": trajectory_tips,
        "driving": driving["notes"],
        "metrics": driving["metrics"],
    }
