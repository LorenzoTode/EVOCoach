"""Anthropic-backed coaching with local heuristic fallback."""

from __future__ import annotations

import json
import os
from typing import Any

SYSTEM_PROMPT = """Sei un race engineer di Assetto Corsa EVO.
Rispondi SOLO in JSON valido (niente markdown) con questa forma:
{
  "summary": "1-2 frasi sul giro",
  "setup": [{
    "severity":"high|medium|low",
    "title":"TC 3 -> 4",
    "menu":"Setup -> Electronics -> Traction Control",
    "parameter":"TC",
    "current":3,
    "target":4,
    "action":"Aumenta TC da 3 a 4 (+1)",
    "detail":"Istruzione precisa da fare nel menu AC EVO",
    "corners":[]
  }],
  "trajectory": [{"severity":"high|medium|low","title":"...","detail":"...","corner":"...","npos":0.0}],
  "driving": [{"severity":"high|medium|low","title":"...","detail":"..."}]
}
Nella sezione setup dai SOLO istruzioni operative del menu AC EVO (Electronics, Differenziale, Ammortizzatori, Gomme)
con valore attuale -> nuovo valore. Max 5 setup, 4 trajectory, 4 driving. Italiano, tecnico, niente filler.
"""


def _heuristic_report(analysis: dict[str, Any]) -> dict[str, Any]:
    final = analysis.get("delta", {}).get("final_delta_ms", 0.0)
    sign = "+" if final >= 0 else ""
    summary = (
        f"Delta vs riferimento {sign}{final/1000:.3f}s. "
        "Priorita: applica le modifiche setup AC EVO, poi le curve dove perdi di piu."
    )
    setup = []
    for t in analysis.get("setup", [])[:6]:
        setup.append(
            {
                "severity": t.get("severity", "medium"),
                "title": t.get("title", "Setup"),
                "detail": t.get("detail", ""),
                "corners": t.get("corners", []),
                "menu": t.get("menu"),
                "parameter": t.get("parameter"),
                "current": t.get("current"),
                "target": t.get("target"),
                "action": t.get("action"),
            }
        )
    trajectory = [
        {
            "severity": t.get("severity", "medium"),
            "title": t.get("title", "Traiettoria"),
            "detail": t.get("detail", ""),
            "corner": t.get("corner"),
            "npos": t.get("npos"),
        }
        for t in analysis.get("trajectory", [])[:4]
    ]
    driving = [
        {
            "severity": t.get("severity", "medium"),
            "title": t.get("title", "Guida"),
            "detail": t.get("detail", ""),
        }
        for t in analysis.get("driving", [])[:4]
    ]
    if not driving:
        driving = [
            {
                "severity": "low",
                "title": "Input puliti",
                "detail": "Nessun pattern critico rilevato: mantieni progressivita su gas e freno.",
            }
        ]
    return {
        "summary": summary,
        "setup": setup,
        "trajectory": trajectory,
        "driving": driving,
        "source": "heuristic",
    }


def _compact_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
    segs = analysis.get("delta", {}).get("segments", [])
    step = max(1, len(segs) // 40)
    slim_delta = [
        {"npos": round(s["npos"], 3), "delta_ms": round(s["delta_ms"], 1)}
        for s in segs[::step]
    ]
    return {
        "meta": analysis.get("meta", {}),
        "final_delta_ms": analysis.get("delta", {}).get("final_delta_ms"),
        "corners": analysis.get("corners", [])[:8],
        "metrics": analysis.get("metrics", {}),
        "setup_signals": analysis.get("setup", [])[:6],
        "trajectory_signals": analysis.get("trajectory", [])[:5],
        "driving_signals": analysis.get("driving", [])[:5],
        "delta_sparklines": slim_delta,
    }


def generate_coach_report(analysis: dict[str, Any], *, force_heuristic: bool = False) -> dict[str, Any]:
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if force_heuristic or not api_key:
        return _heuristic_report(analysis)

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        compact = _compact_analysis(analysis)

        message = client.messages.create(
            model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
            max_tokens=1400,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Analizza questo confronto telemetrico. "
                        "Per l'assetto usa i valori electronics gia letti da AC EVO e proponi "
                        "modifiche menu precise (attuale -> target):\n"
                        + json.dumps(compact, ensure_ascii=False)
                    ),
                }
            ],
        )
        text = ""
        for block in message.content:
            if getattr(block, "type", None) == "text":
                text += block.text
        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:].strip()
        parsed = json.loads(text)
        parsed["source"] = "anthropic"
        for key in ("setup", "trajectory", "driving"):
            parsed.setdefault(key, [])
        local = _heuristic_report(analysis)
        if not parsed.get("setup") or not any(t.get("action") or t.get("menu") for t in parsed["setup"]):
            parsed["setup"] = local["setup"]
        parsed.setdefault("summary", local["summary"])
        return parsed
    except Exception as exc:
        report = _heuristic_report(analysis)
        report["source"] = "heuristic"
        report["warning"] = f"AI non disponibile ({exc.__class__.__name__}): uso analisi locale."
        return report
