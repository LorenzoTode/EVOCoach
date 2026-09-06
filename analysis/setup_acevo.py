"""Precise Assetto Corsa EVO setup menu instructions from live telemetry."""

from __future__ import annotations

from typing import Any


def _num(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _tyre_temps(physics: dict[str, Any]) -> dict[str, float | None]:
    core = physics.get("tyre_core_temp") or physics.get("tyre_temp")
    if not isinstance(core, list) or len(core) < 4:
        return {"fl": None, "fr": None, "rl": None, "rr": None, "front": None, "rear": None}
    vals = [_num(x) for x in core[:4]]
    if any(v is None for v in vals):
        return {"fl": None, "fr": None, "rl": None, "rr": None, "front": None, "rear": None}
    fl, fr, rl, rr = vals  # type: ignore[misc]
    return {
        "fl": fl,
        "fr": fr,
        "rl": rl,
        "rr": rr,
        "front": (fl + fr) / 2,
        "rear": (rl + rr) / 2,
    }


def _pressures(physics: dict[str, Any]) -> dict[str, float | None]:
    p = physics.get("wheels_pressure")
    if not isinstance(p, list) or len(p) < 4:
        return {"front": None, "rear": None}
    vals = [_num(x) for x in p[:4]]
    if any(v is None for v in vals):
        return {"front": None, "rear": None}
    fl, fr, rl, rr = vals  # type: ignore[misc]
    return {"front": (fl + fr) / 2, "rear": (rl + rr) / 2}


def build_acevo_setup_instructions(
    *,
    electronics: dict[str, Any] | None,
    physics: dict[str, Any] | None,
    corner_rank: list[dict[str, Any]] | None = None,
    metrics: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return actionable AC EVO setup/menu steps (current -> change)."""
    electronics = electronics or {}
    physics = physics or {}
    corner_rank = corner_rank or []
    metrics = metrics or {}
    tips: list[dict[str, Any]] = []

    tc = _num(electronics.get("electronics_tc_level"))
    tc_max = _num(electronics.get("electronics_tc_level_max"))
    abs_lvl = _num(electronics.get("electronics_abs_level"))
    abs_max = _num(electronics.get("electronics_abs_level_max"))
    bias = _num(electronics.get("electronics_brake_bias"))
    if bias is None:
        bias = _num(physics.get("brake_bias"))
    bias_pct = None
    if bias is not None:
        bias_pct = bias * 100.0 if bias <= 1.5 else bias

    diff_power = _num(electronics.get("electronics_diff_power"))
    diff_coast = _num(electronics.get("electronics_diff_coast"))
    f_bump = _num(electronics.get("electronics_front_bump_damper"))
    f_reb = _num(electronics.get("electronics_front_rebound_damper"))
    r_bump = _num(electronics.get("electronics_rear_bump_damper"))
    r_reb = _num(electronics.get("electronics_rear_rebound_damper"))
    eng_map = _num(electronics.get("electronics_engine_map"))

    temps = _tyre_temps(physics)
    pressures = _pressures(physics)
    avg_slip = _num(metrics.get("avg_slip")) or 0.0
    max_slip = _num(metrics.get("max_slip")) or 0.0
    slow = [c for c in corner_rank if c.get("loss_ms", 0) > 80][:3]
    entry = [c for c in corner_rank if c.get("loss_ms", 0) > 60][:2]
    fast = [c for c in corner_rank if c.get("loss_ms", 0) > 50 and c.get("speed_gap_kmh", 0) < -4][:3]
    corner_names = lambda xs: [c.get("name") for c in xs if c.get("name")]

    if tc is not None and (max_slip > 0.28 or (avg_slip > 0.12 and slow)):
        target = int(tc) + 1
        if tc_max is not None:
            target = min(target, int(tc_max))
        if target > int(tc):
            tips.append(
                {
                    "severity": "high",
                    "menu": "Setup -> Electronics -> Traction Control",
                    "parameter": "TC",
                    "current": int(tc),
                    "target": target,
                    "action": f"Aumenta TC da {int(tc)} a {target} (+1)",
                    "title": f"TC {int(tc)} -> {target}",
                    "detail": (
                        f"Slip elevato (max {max_slip:.2f}). In AC EVO apri il menu setup, "
                        f"Electronics -> Traction Control, porta il livello a {target}."
                    ),
                    "corners": corner_names(slow),
                }
            )
    elif tc is not None and avg_slip < 0.05 and not slow and int(tc) > 0:
        tips.append(
            {
                "severity": "low",
                "menu": "Setup -> Electronics -> Traction Control",
                "parameter": "TC",
                "current": int(tc),
                "target": max(0, int(tc) - 1),
                "action": f"Prova TC {max(0, int(tc) - 1)} (-1) se vuoi piu trazione libera",
                "title": f"TC {int(tc)} -> {max(0, int(tc) - 1)} (opzionale)",
                "detail": (
                    "Poco slip: puoi abbassare di 1 il TC per guadagnare uscita, "
                    "solo se la macchina non pattina gia."
                ),
                "corners": [],
            }
        )

    if abs_lvl is not None and entry:
        tips.append(
            {
                "severity": "medium",
                "menu": "Setup -> Electronics -> ABS",
                "parameter": "ABS",
                "current": int(abs_lvl),
                "target": int(abs_lvl) + 1 if abs_max is None or int(abs_lvl) < int(abs_max) else int(abs_lvl),
                "action": (
                    f"Se bloccano le anteriori in staccata: ABS {int(abs_lvl)} -> "
                    f"{int(abs_lvl) + 1}. Se la macchina non ruota: lascia ABS e sposta il bias."
                ),
                "title": f"ABS (ora {int(abs_lvl)}) - verifica staccata",
                "detail": (
                    "Perdite in ingresso curva. In AC EVO: Electronics -> ABS. "
                    "Blocchi anteriori = +1 ABS; macchina che non chiude = bias piu posteriore."
                ),
                "corners": corner_names(entry),
            }
        )

    if bias_pct is not None and entry:
        new_bias = round(bias_pct - 0.5, 1)
        tips.append(
            {
                "severity": "high",
                "menu": "Setup -> Electronics -> Brake Bias",
                "parameter": "Brake Bias",
                "current": round(bias_pct, 1),
                "target": new_bias,
                "action": f"Brake Bias {bias_pct:.1f}% -> {new_bias:.1f}% (-0.5% anteriore)",
                "title": f"Brake Bias {bias_pct:.1f}% -> {new_bias:.1f}%",
                "detail": (
                    "Perdi tempo in ingresso. In AC EVO: Electronics -> Brake Bias. "
                    "Sposta di circa -0.5% (piu al posteriore) per aiutare la rotazione; "
                    "se invece bloccano le anteriori, fai il contrario (+0.5%)."
                ),
                "corners": corner_names(entry),
            }
        )

    if diff_power is not None and (max_slip > 0.25 or slow):
        target = int(diff_power) + 1
        tips.append(
            {
                "severity": "high",
                "menu": "Setup -> Differenziale -> Power / Preload",
                "parameter": "Diff Power",
                "current": int(diff_power),
                "target": target,
                "action": f"Diff Power {int(diff_power)} -> {target} (piu chiuso in uscita)",
                "title": f"Diff Power {int(diff_power)} -> {target}",
                "detail": (
                    "Uscite con slip alto. In AC EVO aumenta Diff Power di +1 per chiudere "
                    "il differenziale in accelerazione e stabilizzare la trazione."
                ),
                "corners": corner_names(slow),
            }
        )
    if diff_coast is not None and entry:
        tips.append(
            {
                "severity": "medium",
                "menu": "Setup -> Differenziale -> Coast",
                "parameter": "Diff Coast",
                "current": int(diff_coast),
                "target": max(0, int(diff_coast) - 1),
                "action": f"Diff Coast {int(diff_coast)} -> {max(0, int(diff_coast) - 1)} (piu aperto in rilascio)",
                "title": f"Diff Coast {int(diff_coast)} -> {max(0, int(diff_coast) - 1)}",
                "detail": (
                    "Ingressi difficili: Diff Coast piu basso lascia ruotare meglio l'asse "
                    "posteriore in staccata/rilascio."
                ),
                "corners": corner_names(entry),
            }
        )

    if fast and f_bump is not None and r_bump is not None:
        tips.append(
            {
                "severity": "medium",
                "menu": "Setup -> Ammortizzatori (Bump/Rebound)",
                "parameter": "Dampers",
                "current": f"F bump {int(f_bump)} / R bump {int(r_bump)}",
                "target": f"F {int(f_bump)+1} / R {int(r_bump)+1}",
                "action": "Aumenta bump anteriore e posteriore di +1 per sostegno ad alta velocita",
                "title": "Bump +1 ant/post",
                "detail": (
                    f"Perdite nei tratti veloci. Ora: Front Bump {int(f_bump)}, Rear Bump {int(r_bump)}"
                    + (f", Front Rebound {int(f_reb)}" if f_reb is not None else "")
                    + (f", Rear Rebound {int(r_reb)}" if r_reb is not None else "")
                    + ". In AC EVO alza i bump di 1 click per piu piattaforma."
                ),
                "corners": corner_names(fast),
            }
        )

    if temps["front"] is not None and temps["rear"] is not None:
        front_t, rear_t = temps["front"], temps["rear"]
        if front_t > rear_t + 8:
            tips.append(
                {
                    "severity": "medium",
                    "menu": "Setup -> Gomme -> Pressione / Camber",
                    "parameter": "Tyres",
                    "current": f"T ant {front_t:.0f} / post {rear_t:.0f}",
                    "target": "Riduci carico o pressione anteriore",
                    "action": "Anteriori piu calde: -0.1 / -0.2 psi ant. oppure meno camber negativo davanti",
                    "title": "Gomme anteriori troppo calde",
                    "detail": (
                        f"Core temp ant {front_t:.0f}C vs post {rear_t:.0f}C. "
                        "In AC EVO: Setup gomme - abbassa leggermente la pressione anteriore "
                        "o riduci il camber negativo davanti."
                    ),
                    "corners": [],
                }
            )
        elif rear_t > front_t + 8:
            tips.append(
                {
                    "severity": "medium",
                    "menu": "Setup -> Gomme -> Pressione / Camber",
                    "parameter": "Tyres",
                    "current": f"T ant {front_t:.0f} / post {rear_t:.0f}",
                    "target": "Raffredda il posteriore",
                    "action": "Posteriori piu calde: -0.1 / -0.2 psi post. o +TC / Diff Power",
                    "title": "Gomme posteriori troppo calde",
                    "detail": (
                        f"Core temp post {rear_t:.0f}C vs ant {front_t:.0f}C. "
                        "Spesso e overdrive: abbassa pressione posteriore o alza TC/Diff Power."
                    ),
                    "corners": [],
                }
            )

    if pressures["front"] is not None and pressures["rear"] is not None:
        tips.append(
            {
                "severity": "low",
                "menu": "Setup -> Gomme -> Pressione (riferimento live)",
                "parameter": "Pressure",
                "current": f"{pressures['front']:.1f} / {pressures['rear']:.1f} psi",
                "target": "Mantieni finestra target della vettura",
                "action": f"Pressioni live ant {pressures['front']:.1f} · post {pressures['rear']:.1f} psi",
                "title": "Pressioni attuali",
                "detail": (
                    "Controlla nel menu gomme AC EVO che le pressioni a caldo restino nella "
                    "finestra consigliata per la vettura (di solito ~26-28 psi a caldo in GT3, "
                    "verifica la scheda auto)."
                ),
                "corners": [],
            }
        )

    if eng_map is not None and avg_slip > 0.15:
        tips.append(
            {
                "severity": "low",
                "menu": "Setup -> Electronics -> Engine Map",
                "parameter": "Engine Map",
                "current": int(eng_map),
                "target": int(eng_map) + 1,
                "action": (
                    f"Engine Map piu conservativa: {int(eng_map)} -> {int(eng_map) + 1} "
                    "(se map piu alta = meno potenza)"
                ),
                "title": f"Engine Map (ora {int(eng_map)})",
                "detail": (
                    "Con tanto slip puoi usare una map piu soft in AC EVO (Electronics -> Engine Map) "
                    "per rendere il gas piu gestibile in uscita."
                ),
                "corners": [],
            }
        )

    if not tips and bias_pct is not None:
        tips.append(
            {
                "severity": "low",
                "menu": "Setup -> Electronics (stato attuale)",
                "parameter": "Snapshot",
                "current": f"TC {tc} · ABS {abs_lvl} · Bias {bias_pct:.1f}%",
                "target": "Nessun cambio obbligatorio",
                "action": "Assetto elettronico coerente - lavora su traiettoria/guida",
                "title": "Electronics ok",
                "detail": (
                    f"Valori letti da AC EVO: TC={tc}, ABS={abs_lvl}, "
                    f"Brake Bias={bias_pct:.1f}%, Diff Power={diff_power}, Diff Coast={diff_coast}."
                ),
                "corners": [],
            }
        )

    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for t in tips:
        key = str(t.get("title"))
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
        if len(out) >= 6:
            break
    return out
