"""Anthropic-backed coaching with local heuristic fallback."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5"

SYSTEM_PROMPT = """Sei il race engineer di un pilota su Assetto Corsa EVO. Analizzi la telemetria
di un giro confrontato con un giro di riferimento e dai istruzioni operative.

COME LEGGERE I DATI
- npos: posizione sul giro, 0.0 = linea del traguardo, 1.0 = fine giro.
- final_delta_ms: delta totale in millisecondi. POSITIVO = il pilota e' PIU' LENTO del riferimento.
- loss_zones: i tratti dove il pilota sta attivamente perdendo tempo. loss_ms e' il tempo perso
  in quel solo tratto. Sono ordinate dalla perdita maggiore: qui c'e' il tempo da recuperare.
- corners: curve ordinate per tempo perso, con velocita' in ingresso / apice / uscita
  confrontate con il riferimento (speed_gap_kmh negativo = il pilota e' piu' lento).
- metrics: overlap_pct = % di giro con gas e freno insieme; coast_pct = % di giro in rilascio
  senza gas ne' freno; max_slip = picco di slittamento pneumatici (0-1, sopra 0.35 e' grip perso).
- electronics: i valori ATTUALI letti dal gioco, con il range legale per questa vettura.
- candidate_setup_changes: modifiche gia' calcolate da euristiche locali. Sono CANDIDATE,
  non verita': selezionale, scartale o correggile in base ai dati.

REGOLE NON NEGOZIABILI
1. Ogni valore che proponi deve stare dentro il range legale indicato in electronics.
   Se il range non e' noto, non proporre quel parametro.
2. "current" deve essere il valore realmente letto dal gioco, mai inventato.
3. Ogni "detail" deve citare un numero preso dai dati (ms persi, km/h di gap, %, slip).
   Un consiglio senza numero e' inutile: scartalo.
4. Un problema di tecnica non si risolve con l'assetto. Se overlap_pct, coast_pct o max_slip
   indicano un errore di guida, mettilo in "driving" e NON compensarlo con l'elettronica.
5. Cambia un parametro alla volta per area. Non proporre TC e diff e ammortizzatori insieme
   per lo stesso sintomo: il pilota non saprebbe cosa ha funzionato.
6. Se il pilota e' piu' veloce del riferimento (final_delta_ms negativo), dillo e concentrati
   su dove resta margine, non inventare problemi.

PRIORITA'
Ordina per tempo recuperabile. Una curva da 300 ms viene prima di una da 40 ms.
Se una singola loss_zone vale piu' del 40% del delta totale, il summary deve nominarla.

STILE
Italiano tecnico, seconda persona singolare, niente giri di parole, niente incoraggiamenti.
Massimo 5 setup, 4 trajectory, 4 driving. Meglio 2 consigli precisi che 5 generici.
"""

_TIP_PROPS = {
    "severity": {"type": "string", "enum": ["high", "medium", "low"]},
    "title": {"type": "string", "description": "Etichetta breve, max 60 caratteri"},
    "detail": {"type": "string", "description": "Spiegazione con almeno un numero dai dati"},
}

REPORT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "1-2 frasi sul giro: delta totale e dove si perde di piu'",
        },
        "setup": {
            "type": "array",
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    **_TIP_PROPS,
                    "menu": {
                        "type": "string",
                        "description": "Percorso nel menu AC EVO, es. 'Setup -> Electronics -> Traction Control'",
                    },
                    "parameter": {"type": "string"},
                    "current": {"type": "string", "description": "Valore attuale letto dal gioco"},
                    "target": {"type": "string", "description": "Nuovo valore, dentro il range legale"},
                    "action": {
                        "type": "string",
                        "description": "Istruzione operativa, es. 'Aumenta TC da 3 a 4 (+1)'",
                    },
                },
                "required": [
                    "severity", "title", "detail", "menu",
                    "parameter", "current", "target", "action",
                ],
                "additionalProperties": False,
            },
        },
        "trajectory": {
            "type": "array",
            "maxItems": 4,
            "items": {
                "type": "object",
                "properties": {
                    **_TIP_PROPS,
                    "corner": {"type": "string"},
                    "npos": {"type": "number", "description": "Posizione sul giro, 0.0-1.0"},
                },
                "required": ["severity", "title", "detail", "corner", "npos"],
                "additionalProperties": False,
            },
        },
        "driving": {
            "type": "array",
            "maxItems": 4,
            "items": {
                "type": "object",
                "properties": _TIP_PROPS,
                "required": ["severity", "title", "detail"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "setup", "trajectory", "driving"],
    "additionalProperties": False,
}


# --------------------------------------------------------------------------- #
# Fallback locale
# --------------------------------------------------------------------------- #

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


# --------------------------------------------------------------------------- #
# Costruzione del payload per il modello
# --------------------------------------------------------------------------- #

# Prefissi delle chiavi electronics: valore attuale -> (min, max)
_RANGE_SUFFIXES = ("_min", "_max")


def _electronics_with_ranges(electronics: dict[str, Any]) -> dict[str, Any]:
    """Appaia ogni valore col suo range legale, cosi' il modello non puo' uscirne."""
    out: dict[str, Any] = {}
    for key, value in electronics.items():
        if key.endswith(_RANGE_SUFFIXES):
            continue
        entry: dict[str, Any] = {"current": value}
        lo = electronics.get(f"{key}_min")
        hi = electronics.get(f"{key}_max")
        if lo is not None:
            entry["min"] = lo
        if hi is not None:
            entry["max"] = hi
        out[key.removeprefix("electronics_")] = entry
    return out


def _loss_zones(segments: list[dict[str, Any]], top_n: int = 5) -> list[dict[str, Any]]:
    """Tratti contigui in cui il delta peggiora: dove il tempo si perde davvero.

    Sostituisce il campionamento uniforme della curva delta, che puo' saltare
    esattamente la staccata in cui si perde il tempo.
    """
    if not segments:
        return []

    zones: list[dict[str, Any]] = []
    start: int | None = None
    for i, seg in enumerate(segments):
        losing = (seg.get("instant_ms") or 0.0) > 0
        if losing and start is None:
            start = i
        elif not losing and start is not None:
            zones.append((start, i - 1))
            start = None
    if start is not None:
        zones.append((start, len(segments) - 1))

    scored = []
    for a, b in zones:
        loss = (segments[b].get("delta_ms") or 0.0) - (segments[a].get("delta_ms") or 0.0)
        if loss < 15:  # sotto i 15 ms e' rumore
            continue
        window = segments[a : b + 1]
        speeds = [(s["speed"], s["speed_ref"]) for s in window
                  if s.get("speed") is not None and s.get("speed_ref") is not None]
        gap = (sum(c - r for c, r in speeds) / len(speeds)) if speeds else None
        brakes = [s["brake"] for s in window if s.get("brake") is not None]
        scored.append(
            {
                "from_npos": round(segments[a]["npos"], 3),
                "to_npos": round(segments[b]["npos"], 3),
                "loss_ms": round(loss, 0),
                "speed_gap_kmh": round(gap, 1) if gap is not None else None,
                "max_brake": round(max(brakes), 2) if brakes else None,
            }
        )
    scored.sort(key=lambda z: z["loss_ms"], reverse=True)
    return scored[:top_n]


def _corner_phases(
    segments: list[dict[str, Any]], corners: list[dict[str, Any]], top_n: int = 6
) -> list[dict[str, Any]]:
    """Per ogni curva: ingresso / apice / uscita, confrontati col riferimento.

    Dice al modello *perche'* si perde in curva, non solo quanto.
    """
    out = []
    for corner in corners[:top_n]:
        start, end = corner.get("start"), corner.get("end")
        if start is None or end is None:
            continue
        window = [s for s in segments if start <= s["npos"] <= end]
        if len(window) < 4:
            continue

        def _phase(chunk: list[dict[str, Any]]) -> dict[str, Any]:
            cur = [s["speed"] for s in chunk if s.get("speed") is not None]
            ref = [s["speed_ref"] for s in chunk if s.get("speed_ref") is not None]
            return {
                "speed_kmh": round(sum(cur) / len(cur), 1) if cur else None,
                "ref_kmh": round(sum(ref) / len(ref), 1) if ref else None,
            }

        third = max(1, len(window) // 3)
        apex_i = min(
            range(len(window)),
            key=lambda i: window[i]["speed"] if window[i].get("speed") is not None else 1e9,
        )
        out.append(
            {
                "name": corner.get("name"),
                "loss_ms": round(corner.get("loss_ms", 0.0), 0),
                "entry": _phase(window[:third]),
                "apex": _phase(window[max(0, apex_i - 1) : apex_i + 2]),
                "exit": _phase(window[-third:]),
                "npos": round(corner.get("mid_npos", (start + end) / 2), 3),
            }
        )
    return out


def _compact_analysis(
    analysis: dict[str, Any], history: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    segments = analysis.get("delta", {}).get("segments", [])
    electronics = (analysis.get("meta", {}) or {}).get("electronics") or {}

    payload: dict[str, Any] = {
        "meta": {k: v for k, v in (analysis.get("meta") or {}).items() if k != "electronics"},
        "final_delta_ms": round(analysis.get("delta", {}).get("final_delta_ms") or 0.0, 0),
        "loss_zones": _loss_zones(segments),
        "corners": _corner_phases(segments, analysis.get("corners", [])),
        "metrics": analysis.get("metrics", {}),
        "electronics": _electronics_with_ranges(electronics),
        "candidate_setup_changes": analysis.get("setup", [])[:6],
        "driving_signals": analysis.get("driving", [])[:5],
        "trajectory_signals": analysis.get("trajectory", [])[:5],
    }
    if history:
        payload["previous_laps"] = history[:5]
    return payload


# --------------------------------------------------------------------------- #
# Backend generico "OpenAI-compatibile"
#
# Copre i provider con piano gratuito (Google AI Studio, OpenRouter, Groq) e
# Ollama in locale: parlano tutti lo stesso protocollo. Si attiva impostando
# COACH_BASE_URL nel .env, e ha la precedenza sul backend Anthropic.
#
# Usa la stdlib invece di un SDK: e' una sola richiesta HTTP, non vale una
# dipendenza in piu' su una macchina da gioco.
# --------------------------------------------------------------------------- #

def _schema_without_limits(node: Any) -> Any:
    """Copia dello schema senza maxItems.

    La modalita' strict di molti provider rifiuta i vincoli di cardinalita';
    i limiti restano scritti nel prompt di sistema.
    """
    if isinstance(node, dict):
        return {k: _schema_without_limits(v) for k, v in node.items() if k != "maxItems"}
    if isinstance(node, list):
        return [_schema_without_limits(v) for v in node]
    return node


# Sovraccarico del provider, non un errore della richiesta: vale la pena
# riprovare invece di ripiegare subito sull'analisi locale.
_RETRY_STATUSES = (429, 500, 502, 503, 504)


def _post_json(url: str, payload: dict[str, Any], api_key: str, timeout: float) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _strip_fences(text: str) -> str:
    """Alcuni modelli incorniciano il JSON in un blocco markdown."""
    text = text.strip()
    if not text.startswith("```"):
        return text
    body = text.split("```")
    return body[1].removeprefix("json").strip() if len(body) > 1 else text


def _openai_compat_report(
    analysis: dict[str, Any], history: list[dict[str, Any]] | None
) -> dict[str, Any]:
    base_url = os.getenv("COACH_BASE_URL", "").strip().rstrip("/")
    api_key = os.getenv("COACH_API_KEY", "").strip()
    model = os.getenv("COACH_MODEL", "").strip()
    timeout = float(os.getenv("COACH_TIMEOUT", "120"))
    if not model:
        raise ValueError("COACH_MODEL non impostato")

    compact = _compact_analysis(analysis, history)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Analizza questo giro e dammi il piano di lavoro.\n\n"
                + json.dumps(compact, ensure_ascii=False, sort_keys=True)
            ),
        },
    ]
    base = {"model": model, "messages": messages, "temperature": 0.2}

    # Degradazione progressiva: non tutti i provider supportano lo stesso
    # livello di vincolo sull'output. Si parte dal piu' stretto.
    attempts: list[dict[str, Any]] = [
        {
            **base,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "coach_report",
                    "strict": True,
                    "schema": _schema_without_limits(REPORT_SCHEMA),
                },
            },
        },
        {**base, "response_format": {"type": "json_object"}},
        base,
    ]

    import time

    last_error: Exception | None = None
    for i, payload in enumerate(attempts):
        data = None
        for attempt in range(3):
            try:
                data = _post_json(f"{base_url}/chat/completions", payload, api_key, timeout)
                break
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", "replace")[:300]
                last_error = RuntimeError(f"HTTP {exc.code}: {body}")
                if exc.code in _RETRY_STATUSES and attempt < 2:
                    delay = 2**attempt
                    log.info("Coach: %s dal provider, riprovo fra %ds", exc.code, delay)
                    time.sleep(delay)
                    continue
                if exc.code == 400 and i < len(attempts) - 1:
                    log.info("Coach: response_format non accettato, riprovo piu' permissivo")
                    break
                raise last_error from exc
        if data is None:
            continue

        text = _strip_fences(data["choices"][0]["message"]["content"] or "")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            if i < len(attempts) - 1:
                log.info("Coach: risposta non JSON, riprovo con un vincolo piu' stretto")
                continue
            raise
        usage = data.get("usage") or {}
        log.info(
            "Coach: %s (%s) in=%s out=%s",
            model, base_url,
            usage.get("prompt_tokens", "?"), usage.get("completion_tokens", "?"),
        )
        return parsed

    raise last_error or RuntimeError("nessuna risposta utilizzabile")


# --------------------------------------------------------------------------- #
# Chiamata al modello
# --------------------------------------------------------------------------- #

_client = None


def _get_client(api_key: str):
    global _client
    if _client is None:
        import anthropic

        _client = anthropic.Anthropic(api_key=api_key)
    return _client


def _fallback(analysis: dict[str, Any], warning: str | None = None) -> dict[str, Any]:
    report = _heuristic_report(analysis)
    report["source"] = "heuristic"
    if warning:
        report["warning"] = warning
    return report


def generate_coach_report(
    analysis: dict[str, Any],
    *,
    force_heuristic: bool = False,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Report di coaching. Usa Claude se c'e' una API key, altrimenti l'euristica locale.

    history: giri precedenti sulla stessa pista, cosi' il coach vede la progressione
    invece di ripartire da zero a ogni giro.
    """
    if force_heuristic:
        return _heuristic_report(analysis)

    # Backend generico (Google AI Studio, OpenRouter, Groq, Ollama...): se
    # COACH_BASE_URL e' configurato ha la precedenza su Anthropic.
    if os.getenv("COACH_BASE_URL", "").strip():
        try:
            parsed = _openai_compat_report(analysis, history)
            parsed["source"] = "openai_compat"
            parsed["model"] = os.getenv("COACH_MODEL", "")
            local = _heuristic_report(analysis)
            for key in ("setup", "trajectory", "driving"):
                parsed.setdefault(key, [])
            if not parsed.get("setup"):
                parsed["setup"] = local["setup"]
            parsed.setdefault("summary", local["summary"])
            return parsed
        except (
            urllib.error.URLError,
            TimeoutError,
            RuntimeError,
            ValueError,
            KeyError,
            IndexError,
        ) as exc:
            log.warning("Coach: backend esterno non disponibile — %s", exc)
            return _fallback(analysis, f"AI esterna non disponibile: {str(exc)[:140]}")

    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return _heuristic_report(analysis)

    import anthropic

    try:
        client = _get_client(api_key)
        compact = _compact_analysis(analysis, history)

        model = os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL)
        request: dict[str, Any] = {
            "model": model,
            "max_tokens": 16000,
            "system": SYSTEM_PROMPT,
            "output_config": {"format": {"type": "json_schema", "schema": REPORT_SCHEMA}},
        }
        # Haiku 4.5 non supporta ne' il thinking adaptive ne' output_config.effort:
        # con quei parametri l'API risponde 400. Sui modelli che li accettano
        # valgono la spesa: il compito e' ragionamento su numeri.
        if "haiku" not in model:
            request["thinking"] = {"type": "adaptive"}
            request["output_config"]["effort"] = os.getenv("ANTHROPIC_EFFORT", "high")

        message = client.messages.create(
            **request,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Analizza questo giro e dammi il piano di lavoro.\n\n"
                        + json.dumps(compact, ensure_ascii=False, sort_keys=True)
                    ),
                }
            ],
        )

        if message.stop_reason == "refusal":
            detail = getattr(message.stop_details, "explanation", None) or "nessun dettaglio"
            log.warning("Coach: richiesta rifiutata dal modello (%s)", detail)
            return _fallback(analysis, "Il modello ha rifiutato la richiesta: uso analisi locale.")

        if message.stop_reason == "max_tokens":
            log.warning("Coach: risposta troncata a max_tokens, alzare il limite")
            return _fallback(analysis, "Risposta AI troncata: uso analisi locale.")

        log.info(
            "Coach: %s in=%d out=%d cache_read=%d",
            message.model,
            message.usage.input_tokens,
            message.usage.output_tokens,
            message.usage.cache_read_input_tokens or 0,
        )

        # output_config.format garantisce JSON valido conforme allo schema
        text = next(b.text for b in message.content if b.type == "text")
        parsed = json.loads(text)
        parsed["source"] = "anthropic"

        # L'euristica resta la rete di sicurezza sui setup: se il modello non ha
        # prodotto istruzioni operative, si usano quelle calcolate localmente.
        if not parsed.get("setup"):
            parsed["setup"] = _heuristic_report(analysis)["setup"]
        return parsed

    except anthropic.AuthenticationError:
        log.error("Coach: ANTHROPIC_API_KEY non valida")
        return _fallback(analysis, "API key Anthropic non valida: uso analisi locale.")
    except anthropic.RateLimitError:
        log.warning("Coach: rate limit Anthropic")
        return _fallback(analysis, "Limite di richieste raggiunto: uso analisi locale.")
    except anthropic.BadRequestError as exc:
        # Tipicamente: parametro non supportato dal modello configurato.
        log.error("Coach: richiesta rifiutata dall'API — %s", exc.message)
        return _fallback(analysis, f"Richiesta AI non valida: {exc.message[:120]}")
    except anthropic.APIConnectionError:
        log.warning("Coach: nessuna connessione all'API Anthropic")
        return _fallback(analysis, "Nessuna connessione all'AI: uso analisi locale.")
    except anthropic.APIStatusError as exc:
        log.error("Coach: errore API %s", exc.status_code)
        return _fallback(analysis, f"Errore AI ({exc.status_code}): uso analisi locale.")
    except (json.JSONDecodeError, StopIteration, KeyError, ValueError) as exc:
        log.exception("Coach: risposta AI non interpretabile")
        return _fallback(analysis, f"Risposta AI non valida ({type(exc).__name__}): uso analisi locale.")
