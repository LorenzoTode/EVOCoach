"""Profilo di guida: cosa il pilota fa *sempre*, non cosa ha fatto in un giro.

Un consiglio su un giro solo confonde il caso con l'abitudine. Un pilota che
in una curva apre presto puo' aver sbagliato; uno che apre presto in sette
curve su nove ha un modo di guidare, e va corretto in modo diverso.

Le metriche per giro si calcolano alla chiusura del giro e si conservano nel
suo record; qui si aggregano sulla mediana degli ultimi giri validi, che
regge meglio della media a un singolo giro anomalo.
"""

from __future__ import annotations

import statistics
from typing import Any

import numpy as np

from analysis.delta import resample_to_grid

# Quanti giri guardare all'indietro. Abbastanza per vedere un'abitudine,
# pochi da seguire i miglioramenti invece di annegarli nella storia.
PROFILE_WINDOW = 12

# Soglie oltre le quali un comportamento smette di essere rumore e diventa
# un tratto. Ricavate dalle stesse soglie gia' usate in driving_signals.
_TRAITS = (
    ("overlap_pct", 4.0, "high", "Sovrapposizione gas/freno",
     "Freni e acceleri insieme sul {value:.0f}% del giro: la vettura non si stabilizza mai in ingresso."),
    ("coast_pct", 8.0, "medium", "Rilascio lungo",
     "Passi il {value:.0f}% del giro senza gas ne' freno: tempo morto, o freni troppo presto o entri troppo piano."),
    ("max_slip", 0.35, "high", "Gomme oltre il limite",
     "Picco di slittamento a {value:.2f}: stai chiedendo piu' aderenza di quella disponibile."),
    ("early_throttle_pct", 30.0, "medium", "Gas anticipato",
     "Apri il gas presto nel {value:.0f}% delle curve: sottosterzo in uscita e traiettoria allargata."),
    ("brake_peak", 0.97, "medium", "Staccata sempre al massimo",
     "Freni a fondo (picco {value:.2f}) quasi ovunque: poco margine per modulare in rilascio."),
)


def lap_metrics(samples: list[dict[str, Any]], corners: list[dict[str, Any]]) -> dict[str, float]:
    """Metriche di comportamento di un singolo giro."""
    if len(samples) < 30:
        return {}

    grid = resample_to_grid(
        samples, ["speed", "gas", "brake", "steer", "slip_fl", "slip_fr", "slip_rl", "slip_rr"], n=300
    )
    brake, gas, speed, steer = grid["brake"], grid["gas"], grid["speed"], grid["steer"]
    npos = grid["npos"]

    overlap = np.logical_and(brake > 0.15, gas > 0.15)
    coasting = np.logical_and(brake < 0.05, gas < 0.08, speed > 80)
    slips = np.concatenate([grid[k] for k in ("slip_fl", "slip_fr", "slip_rl", "slip_rr")])
    slips = slips[np.isfinite(slips)]

    braking = brake[brake > 0.2]
    # Frenata in curva: quanto si resta sul freno mentre si sterza gia'.
    trail = np.logical_and(brake > 0.2, np.abs(steer) > 0.15)

    early = 0
    considered = 0
    for corner in corners:
        mask = (npos >= corner["start"]) & (npos <= corner["end"])
        if not np.any(mask):
            continue
        b, g = brake[mask], gas[mask]
        if len(b) < 4:
            continue
        considered += 1
        peak = int(np.argmax(b))
        after = g[peak:]
        # Gas oltre il 60% entro il primo terzo dopo il picco di frenata.
        if len(after) and float(np.max(after)) > 0.6 and peak < len(b) * 0.35:
            early += 1

    return {
        "overlap_pct": round(float(np.mean(overlap)) * 100, 1),
        "coast_pct": round(float(np.mean(coasting)) * 100, 1),
        "trail_brake_pct": round(float(np.mean(trail)) * 100, 1),
        "avg_slip": round(float(np.mean(slips)), 3) if slips.size else 0.0,
        "max_slip": round(float(np.max(slips)), 3) if slips.size else 0.0,
        "brake_peak": round(float(np.max(braking)), 2) if braking.size else 0.0,
        "brake_time_pct": round(float(np.mean(brake > 0.2)) * 100, 1),
        "early_throttle_pct": round(100.0 * early / considered, 1) if considered else 0.0,
        "avg_speed": round(float(np.nanmean(speed)), 1),
    }


def build_driver_profile(laps: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggrega le metriche dei giri validi in un profilo.

    laps: record di giro con 'lap_time_ms' e 'metrics' (da lap_metrics).
    """
    scored = [lap for lap in laps if lap.get("metrics") and lap.get("lap_time_ms")][:PROFILE_WINDOW]
    if len(scored) < 2:
        return {"laps": len(scored), "ready": False}

    def median_of(key: str) -> float:
        vals = [float(l["metrics"][key]) for l in scored if key in l["metrics"]]
        return round(statistics.median(vals), 2) if vals else 0.0

    times = [int(l["lap_time_ms"]) for l in scored]
    best = min(times)
    # Costanza: quanto ci si allontana dal proprio riferimento, in media.
    spread = round(statistics.mean(t - best for t in times) / 1000, 3)

    habits = {key: median_of(key) for key, *_ in _TRAITS}
    habits["trail_brake_pct"] = median_of("trail_brake_pct")
    habits["brake_time_pct"] = median_of("brake_time_pct")

    traits = [
        {
            "severity": severity,
            "title": title,
            "detail": template.format(value=habits[key]),
            "metric": key,
            "value": habits[key],
        }
        for key, threshold, severity, title, template in _TRAITS
        if habits.get(key, 0) > threshold
    ]

    # La tendenza si legge sui giri, non sulle sensazioni: meta' piu' recente
    # contro meta' piu' vecchia.
    trend = None
    if len(times) >= 4:
        half = len(times) // 2
        recent, older = statistics.median(times[:half]), statistics.median(times[half:])
        trend = round((recent - older) / 1000, 3)

    return {
        "ready": True,
        "laps": len(scored),
        "best_ms": best,
        "consistenza_s": spread,
        "tendenza_s": trend,
        "abitudini": habits,
        "tratti": traits,
    }
