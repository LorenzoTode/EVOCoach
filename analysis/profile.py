"""Profilo di guida: dove sbagli, quanto ti costa, e cosa fare per toglierlo.

Un giro solo confonde l'episodio con l'abitudine. Ma sapere di avere
un'abitudine non basta a cambiarla: servono il punto della pista in cui si
manifesta, il tempo che vale, e un esercizio concreto da provare nel giro
dopo. Questo modulo produce quelle tre cose a partire dai giri gia' archiviati.
"""

from __future__ import annotations

import statistics
from typing import Any

import numpy as np

from analysis.delta import resample_to_grid

# Abbastanza giri da vedere un'abitudine, pochi da seguire i miglioramenti
# invece di annegarli nella storia.
PROFILE_WINDOW = 12

# Ogni tratto sa: come si misura, quando smette di essere rumore, come si
# chiama, cosa significa, e — la parte che mancava — cosa fare per toglierlo.
# Gli esercizi sono deliberatamente concreti e verificabili in un paio di giri:
# "sii piu' fluido" non e' un esercizio.
TRAITS: tuple[dict[str, Any], ...] = (
    {
        "key": "overlap_pct",
        "corner_key": "overlap",
        "threshold": 4.0,
        "severity": "high",
        "title": "Freno e gas insieme",
        "detail": "Sovrapponi i pedali sul {value:.0f}% del giro. Finche' il freno e' premuto "
                  "il gas non trasferisce carico: la vettura resta sospesa fra due comandi "
                  "opposti e non si stabilizza mai in ingresso.",
        "drill": "Per due giri interi stacca completamente il piede dal freno PRIMA di toccare "
                 "il gas, anche perdendo tempo. Serve a sentire il momento in cui la vettura "
                 "si posa. Poi riavvicina i due comandi finche' non ricompare il sintomo.",
        "check": "L'overlap deve scendere sotto il 4%.",
        "setup": {
            "parameter": "ABS",
            "key": "abs_level",
            "menu": "Setup -> Electronics -> ABS",
            "step": +1,
            "effect": "stabilita' in ingresso mentre correggi la tecnica",
            "caveat": "L'assetto qui nasconde il sintomo, non lo toglie: l'esercizio resta la cura.",
        },
    },
    {
        "key": "coast_pct",
        "corner_key": "coast",
        "threshold": 8.0,
        "severity": "medium",
        "title": "Troppo tempo senza pedali",
        "detail": "Passi il {value:.0f}% del giro in rilascio, ne' gas ne' freno. E' tempo in cui "
                  "la vettura rallenta senza che tu lo stia decidendo: o freni troppo presto, "
                  "o entri troppo piano e aspetti.",
        "drill": "Scegli UNA curva e ritarda il punto di frenata di una tacca alla volta — un "
                 "cartello, una riga d'asfalto — finche' non arrivi al gas subito dopo il "
                 "rilascio del freno, senza tratti morti.",
        "check": "Il rilascio deve scendere sotto l'8% senza aumentare l'overlap.",
        "setup": None,   # non e' un problema di assetto: e' il punto di frenata
    },
    {
        "key": "max_slip",
        "corner_key": "slip",
        "threshold": 0.35,
        "severity": "high",
        "title": "Gomme oltre aderenza",
        "detail": "Picco di slittamento a {value:.2f}. Sopra 0.35 lo pneumatico striscia invece "
                  "di rotolare: perdi tempo mentre sembra che tu ne stia guadagnando, e "
                  "surriscaldi la gomma per i giri successivi.",
        "drill": "Nella curva peggiore entra 5 km/h piu' piano e apri il gas mezzo secondo dopo. "
                 "Se il tempo sul settore migliora, non era velocita': era pattinamento.",
        "check": "Il picco deve stare sotto 0.35 con lo stesso tempo sul giro.",
        "setup": {
            "parameter": "TC",
            "key": "tc_level",
            "menu": "Setup -> Electronics -> Traction Control",
            "step": +1,
            "effect": "meno pattinamento in uscita",
            "caveat": "",
        },
    },
    {
        "key": "early_throttle_pct",
        "corner_key": "early_throttle",
        "threshold": 30.0,
        "severity": "medium",
        "title": "Gas troppo presto",
        "detail": "Apri il gas subito dopo il picco di frenata nel {value:.0f}% delle curve. "
                  "La vettura non ha ancora finito di ruotare: allarghi, e per rientrare devi "
                  "chiudere il gas — perdendo due volte.",
        "drill": "Aspetta di vedere l'uscita della curva prima di aprire. Come riferimento: "
                 "il gas si apre quando puoi tenerlo aperto fino in fondo senza correggere.",
        "check": "Meno del 30% delle curve, e velocita' in uscita piu' alta di prima.",
        "setup": {
            "parameter": "Diff Power",
            "key": "diff_power",
            "menu": "Setup -> Differenziale -> Power",
            "step": +5,
            "effect": "trazione in uscita quando apri presto",
            "caveat": "Chiude anche la rotazione: se allarghi di piu', torna indietro.",
        },
    },
    {
        "key": "brake_peak",
        "corner_key": "hard_brake",
        "threshold": 0.97,
        "severity": "medium",
        "title": "Sempre a fondo sul freno",
        "detail": "Picco di frenata a {value:.2f} quasi ovunque. Frenare a fondo va bene in "
                  "staccata dritta, ma se non rilasci progressivamente entrando la vettura "
                  "arriva all'inserimento ancora scarica dietro.",
        "drill": "Frena forte all'inizio e rilascia gradualmente verso la corda, invece di "
                 "tenere la stessa pressione e mollare di colpo. Il freno deve accompagnare "
                 "lo sterzo, non finire prima.",
        "check": "Il freno in curva deve salire, il picco puo' restare alto.",
        "setup": {
            "parameter": "Brake Bias",
            "key": "brake_bias",
            "menu": "Setup -> Electronics -> Brake Bias",
            "step": -0.5,
            "effect": "meno bloccaggio anteriore in staccata piena",
            "caveat": "",
        },
    },
    {
        "key": "trail_brake_pct",
        "corner_key": "trail",
        "threshold": 0.0,          # informativo: non e' un difetto, e' uno stile
        "severity": "low",
        "title": "Frenata in curva",
        "detail": "Resti sul freno mentre sterzi nel {value:.0f}% del giro.",
        "drill": "",
        "check": "",
        "informational": True,
    },
)


def _corner_of(npos: float, corners: list[dict[str, Any]]) -> str | None:
    for c in corners:
        if c["start"] <= npos <= c["end"]:
            return c.get("name")
    return None


def lap_metrics(samples: list[dict[str, Any]], corners: list[dict[str, Any]]) -> dict[str, Any]:
    """Comportamento di un giro, complessivo e curva per curva."""
    if len(samples) < 30:
        return {}

    grid = resample_to_grid(
        samples, ["speed", "gas", "brake", "steer", "slip_fl", "slip_fr", "slip_rl", "slip_rr"], n=300
    )
    brake, gas, speed, steer, npos = grid["brake"], grid["gas"], grid["speed"], grid["steer"], grid["npos"]
    slip_stack = np.vstack([grid[k] for k in ("slip_fl", "slip_fr", "slip_rl", "slip_rr")])
    slip_max_per_point = np.nanmax(slip_stack, axis=0)

    overlap = np.logical_and(brake > 0.15, gas > 0.15)
    coasting = np.logical_and(brake < 0.05, gas < 0.08, speed > 80)
    trail = np.logical_and(brake > 0.2, np.abs(steer) > 0.15)
    braking = brake[brake > 0.2]
    slips = slip_stack[np.isfinite(slip_stack)]

    # Dove succede: senza il punto della pista, un'abitudine non e' correggibile.
    per_corner: dict[str, dict[str, Any]] = {}
    early = considered = 0
    for corner in corners:
        name = corner.get("name")
        if not name:
            continue
        mask = (npos >= corner["start"]) & (npos <= corner["end"])
        if not np.any(mask) or int(np.sum(mask)) < 4:
            continue
        b, g = brake[mask], gas[mask]
        considered += 1
        peak = int(np.argmax(b))
        after = g[peak:]
        is_early = bool(len(after) and float(np.max(after)) > 0.6 and peak < len(b) * 0.35)
        early += is_early
        per_corner[name] = {
            "overlap": round(float(np.mean(overlap[mask])) * 100, 1),
            "coast": round(float(np.mean(coasting[mask])) * 100, 1),
            "trail": round(float(np.mean(trail[mask])) * 100, 1),
            "slip": round(float(np.nanmax(slip_max_per_point[mask])), 3),
            "early_throttle": 100.0 if is_early else 0.0,
            "hard_brake": round(float(np.max(b)), 2),
        }

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
        "per_corner": per_corner,
    }


def _worst_corners(laps: list[dict[str, Any]], corner_key: str, limit: int = 3) -> list[dict[str, Any]]:
    """Le curve in cui il comportamento si manifesta di piu', sulla mediana."""
    acc: dict[str, list[float]] = {}
    for lap in laps:
        for name, values in (lap["metrics"].get("per_corner") or {}).items():
            if corner_key in values:
                acc.setdefault(name, []).append(float(values[corner_key]))
    ranked = [
        {"name": name, "value": round(statistics.median(vals), 1), "laps": len(vals)}
        for name, vals in acc.items()
        if vals and statistics.median(vals) > 0
    ]
    ranked.sort(key=lambda c: c["value"], reverse=True)
    return ranked[:limit]


def build_driver_profile(laps: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggrega i giri validi in un profilo con dove, quanto e come correggere."""
    scored = [l for l in laps if l.get("metrics") and l.get("lap_time_ms")][:PROFILE_WINDOW]
    if len(scored) < 2:
        return {"laps": len(scored), "ready": False}

    def median_of(key: str) -> float:
        vals = [float(l["metrics"][key]) for l in scored if key in l["metrics"]]
        return round(statistics.median(vals), 2) if vals else 0.0

    def trend_of(key: str) -> float | None:
        """Mediana dei giri recenti meno quella dei piu' vecchi: negativo = migliora."""
        vals = [float(l["metrics"][key]) for l in scored if key in l["metrics"]]
        if len(vals) < 4:
            return None
        half = len(vals) // 2
        return round(statistics.median(vals[:half]) - statistics.median(vals[half:]), 2)

    times = [int(l["lap_time_ms"]) for l in scored]
    best = min(times)
    habits = {t["key"]: median_of(t["key"]) for t in TRAITS}
    habits["brake_time_pct"] = median_of("brake_time_pct")

    traits = []
    for spec in TRAITS:
        if spec.get("informational"):
            continue
        value = habits.get(spec["key"], 0.0)
        if value <= spec["threshold"]:
            continue
        traits.append(
            {
                "severity": spec["severity"],
                "title": spec["title"],
                "detail": spec["detail"].format(value=value),
                "metric": spec["key"],
                "value": value,
                "trend": trend_of(spec["key"]),
                "corners": _worst_corners(scored, spec["corner_key"]),
                "drill": spec["drill"],
                "check": spec["check"],
            }
        )
    traits.sort(key=lambda t: ({"high": 0, "medium": 1, "low": 2}[t["severity"]], -t["value"]))

    trend_time = None
    if len(times) >= 4:
        half = len(times) // 2
        trend_time = round((statistics.median(times[:half]) - statistics.median(times[half:])) / 1000, 3)

    return {
        "ready": True,
        "laps": len(scored),
        "best_ms": best,
        "consistenza_s": round(statistics.mean(t - best for t in times) / 1000, 3),
        "tendenza_s": trend_time,
        "abitudini": habits,
        "tratti": traits,
    }


def attach_cost(profile: dict[str, Any], corners: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggiunge a ogni tratto il tempo perso nelle curve in cui si manifesta.

    E' una correlazione, non una prova di causa: il vizio e la perdita di tempo
    stanno nelle stesse curve. Serve a dare un ordine di grandezza — "qui vale
    quasi un secondo" pesa diversamente da "qui vale tre centesimi".
    """
    if not profile.get("ready"):
        return profile
    losses = {c.get("name"): c.get("loss_ms", 0.0) for c in corners}
    tratti = [
        {
            **t,
            "tempo_perso_in_quelle_curve_ms": round(
                sum(max(0.0, float(losses.get(c["name"]) or 0.0)) for c in t.get("corners", []))
            ),
        }
        for t in profile.get("tratti", [])
    ]
    return {**profile, "tratti": tratti}


def _electronic(electronics: dict[str, Any], key: str) -> tuple[float | None, float | None, float | None]:
    """Valore attuale e range legale di un parametro, come li pubblica il gioco."""
    value = electronics.get(f"electronics_{key}")
    lo = electronics.get(f"electronics_{key}_min")
    hi = electronics.get(f"electronics_{key}_max")
    return (
        float(value) if isinstance(value, (int, float)) else None,
        float(lo) if isinstance(lo, (int, float)) else None,
        float(hi) if isinstance(hi, (int, float)) else None,
    )


def setup_from_profile(
    profile: dict[str, Any], electronics: dict[str, Any]
) -> list[dict[str, Any]]:
    """Modifiche d'assetto che nascono dalle abitudini, non dal singolo giro.

    Ogni voce dichiara da cosa nasce: e' la catena abitudine -> conseguenza ->
    modifica, resa esplicita e verificabile. Restano dentro il range legale
    letto dal gioco; senza il valore attuale non si propone nulla, perche' un
    target senza un "da" non e' un'istruzione.
    """
    if not profile.get("ready"):
        return []

    by_key = {spec["key"]: spec for spec in TRAITS}
    out: list[dict[str, Any]] = []

    for trait in profile.get("tratti", []):
        spec = by_key.get(trait.get("metric"))
        hint = (spec or {}).get("setup")
        if not hint:
            continue
        current, lo, hi = _electronic(electronics, hint["key"])
        if current is None:
            continue
        target = current + hint["step"]
        if lo is not None:
            target = max(lo, target)
        if hi is not None:
            target = min(hi, target)
        if abs(target - current) < 1e-6:
            continue   # gia' al limite: proporlo sarebbe un consiglio finto

        fmt = (lambda v: f"{v:.1f}") if isinstance(hint["step"], float) else (lambda v: f"{v:.0f}")
        detail = (
            f"Nasce dal profilo: {trait['title'].lower()} — {trait['detail'].split('.')[0].lower()}. "
            f"Portare {hint['parameter']} a {fmt(target)} da' {hint['effect']}."
        )
        if hint.get("caveat"):
            detail += f" {hint['caveat']}"

        out.append(
            {
                "severity": trait["severity"],
                "title": f"{hint['parameter']} {fmt(current)} -> {fmt(target)}",
                "menu": hint["menu"],
                "parameter": hint["parameter"],
                "current": fmt(current),
                "target": fmt(target),
                "action": f"Porta {hint['parameter']} da {fmt(current)} a {fmt(target)}",
                "detail": detail,
                "because": trait["detail"].split(".")[0] + ".",
                "from_profile": True,
                "trait": trait["metric"],
                "corners": [c["name"] for c in trait.get("corners", [])],
            }
        )
    return out
