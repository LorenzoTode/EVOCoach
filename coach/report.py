"""Anthropic-backed coaching with local heuristic fallback."""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5"

SYSTEM_PROMPT = """Sei il race engineer di un pilota su Assetto Corsa EVO.

COME LEGGERE I DATI
npos: posizione sul giro, 0.0 = traguardo. final_delta_ms POSITIVO = il pilota e' PIU' LENTO.
loss_zones: tratti dove sta perdendo tempo, ordinati per perdita. corners: curve con velocita'
in ingresso/apice/uscita contro il riferimento. metrics: overlap_pct = gas e freno insieme;
coast_pct = ne' gas ne' freno; max_slip sopra 0.35 = aderenza persa. electronics: valori
ATTUALI dal gioco col range legale. candidate_setup_changes: proposte gia' calcolate, da
selezionare o scartare, non verita'.
profilo: come guida SEMPRE, non com'e' andato oggi. "tratti" = vizi ricorrenti, ognuno con le
curve dove succede, il tempo perso li' (correlazione, non causa), un "drill" gia' scritto e un
"check". "consistenza_s" = distacco medio dal proprio miglior giro.

REGOLE
1. Ogni valore proposto deve stare nel range legale di electronics. Range ignoto = non proporlo.
2. "current" e' il valore letto dal gioco, mai inventato.
3. Ogni "detail" e ogni "because" citano un numero dei dati. Senza numero, scarta la voce.
4. Un errore di tecnica non si corregge con l'assetto: mettilo in "driving".
5. Un parametro alla volta per sintomo, o non si capisce cosa ha funzionato.
6. Se final_delta_ms e' negativo il pilota e' piu' veloce: dillo, non inventare problemi.
7. Un vizio nei "tratti" e' un'abitudine, un errore isolato e' un episodio: trattali diversamente.
8. Costruisci l'assetto su come guida davvero: chi apre presto vuole trazione in uscita, chi
   frena a fondo stabilita' in staccata, chi sovrappone i pedali stabilita' in ingresso, chi
   resta in rilascio non ha un problema di assetto ma di punto di frenata. Quando l'abitudine
   e' la causa, di' che l'assetto la nasconde e affianca il "drill" del profilo, senza inventarne.
9. Se "consistenza_s" supera 1 secondo la priorita' non e' l'assetto: e' ripetere lo stesso giro.
10. Ordina per tempo recuperabile. Se una loss_zone vale oltre il 40% del delta, nominala nel summary.

LUNGHEZZA — vincoli, non preferenze
Massimo 3 voci in setup, 3 in trajectory, 3 in driving. Meglio 2 precise che 3 generiche.
"detail" e "because": una frase, massimo 20 parole. "title": massimo 6 parole.
"summary": massimo 2 frasi. Italiano tecnico, seconda persona, niente incoraggiamenti.
"""

# Serve solo quando lo schema non viene applicato dal provider: un modello
# piccolo, lasciato senza vincolo, non sa che forma deve avere la risposta.
FORMATO_JSON = """
Rispondi SOLO con JSON valido, niente markdown, niente testo prima o dopo.
{"summary":"...","driver_note":"...",
 "setup":[{"severity":"high|medium|low","title":"...","detail":"...","menu":"...",
           "parameter":"...","current":"...","target":"...","action":"...","because":"..."}],
 "trajectory":[{"severity":"...","title":"...","detail":"...","corner":"...","npos":0.5}],
 "driving":[{"severity":"...","title":"...","detail":"..."}]}
Liste vuote [] se non hai dati sufficienti.
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
            "maxItems": 3,
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
                    "because": {
                        "type": "string",
                        "description": (
                            "Da cosa nasce questa modifica. Se viene da un'abitudine del "
                            "profilo, nominala e cita il numero: 'apri il gas presto nel 60% "
                            "delle curve'. Se viene da un dato del giro, cita quel dato. "
                            "Mai una motivazione generica."
                        ),
                    },
                },
                "required": [
                    "severity", "title", "detail", "menu",
                    "parameter", "current", "target", "action", "because",
                ],
                "additionalProperties": False,
            },
        },
        "trajectory": {
            "type": "array",
            "maxItems": 3,
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
        "driver_note": {
            "type": "string",
            "description": (
                "1-2 frasi su come guida questo pilota secondo il profilo, e su cosa "
                "cambia di conseguenza. Se il profilo non e' pronto, dillo in una frase."
            ),
        },
        "driving": {
            "type": "array",
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": _TIP_PROPS,
                "required": ["severity", "title", "detail"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "driver_note", "setup", "trajectory", "driving"],
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
    analysis: dict[str, Any],
    history: list[dict[str, Any]] | None = None,
    profile: dict[str, Any] | None = None,
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
    if profile and profile.get("ready"):
        payload["profilo"] = profile
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


def _parse_json_loose(text: str) -> dict[str, Any] | None:
    """JSON dalla risposta, anche se il modello ci ha messo del testo intorno.

    I modelli piccoli premettono volentieri una frase di cortesia al JSON.
    Buttare via una risposta buona per quella e' uno spreco: si cerca il primo
    '{' e l'ultimo '}' e si riprova.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    inizio, fine = text.find("{"), text.rfind("}")
    if inizio < 0 or fine <= inizio:
        return None
    try:
        return json.loads(text[inizio : fine + 1])
    except json.JSONDecodeError:
        return None


def _strip_fences(text: str) -> str:
    """Alcuni modelli incorniciano il JSON in un blocco markdown."""
    text = text.strip()
    if not text.startswith("```"):
        return text
    body = text.split("```")
    return body[1].removeprefix("json").strip() if len(body) > 1 else text


def _openai_compat_report(
    analysis: dict[str, Any],
    history: list[dict[str, Any]] | None,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base_url = os.getenv("COACH_BASE_URL", "").strip().rstrip("/")
    api_key = os.getenv("COACH_API_KEY", "").strip()
    model = os.getenv("COACH_MODEL", "").strip()
    # 90s: a 100 tok/s una risposta buona ne impiega 15, a 25 tok/s (CPU) circa
    # 40. Oltre non sta generando, sta ripetendosi.
    timeout = float(os.getenv("COACH_TIMEOUT", "90"))
    max_tokens = int(os.getenv("COACH_MAX_TOKENS", "1400"))
    if not model:
        raise ValueError("COACH_MODEL non impostato")

    compact = _compact_analysis(analysis, history, profile)
    dati = json.dumps(compact, ensure_ascii=False, sort_keys=True)

    def messaggi(con_formato: bool) -> list[dict[str, str]]:
        """Il formato si spiega solo quando lo schema non lo impone gia'."""
        richiesta = "Analizza questo giro e dammi il piano di lavoro."
        if con_formato:
            richiesta += "\n" + FORMATO_JSON
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"{richiesta}\n\nDATI:\n{dati}"},
        ]

    base = {
        "model": model,
        # Zero: il compito e' selezionare e riferire dati, non inventare.
        "temperature": 0,
        # Un tetto esplicito: senza, un modello piccolo puo' produrre venti
        # voci di setup invece di cinque e triplicare il tempo di risposta.
        "max_tokens": max_tokens,
    }

    # Degradazione progressiva: non tutti i provider supportano lo stesso
    # livello di vincolo sull'output. Si parte dal piu' stretto.
    attempts: list[dict[str, Any]] = [
        {
            **base,
            "messages": messaggi(False),
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "coach_report", "strict": True, "schema": REPORT_SCHEMA},
            },
        },
        {
            **base,
            "messages": messaggi(False),
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "coach_report",
                    "strict": True,
                    "schema": _schema_without_limits(REPORT_SCHEMA),
                },
            },
        },
        # Da qui in giu' nessuno impone la forma: va scritta nel messaggio.
        {**base, "messages": messaggi(True), "response_format": {"type": "json_object"}},
        {**base, "messages": messaggi(True)},
    ]

    # Il timeout vale per l'intera analisi, non per ogni tentativo: con quattro
    # livelli di degradazione e tre riprove ciascuno, un timeout per richiesta
    # diventa dieci minuti di attesa. Chi aspetta un report a fine giro ha un
    # solo budget, e va speso tutto insieme.
    scadenza = time.monotonic() + timeout

    def rimanente() -> float:
        return scadenza - time.monotonic()

    last_error: Exception | None = None
    for i, payload in enumerate(attempts):
        data = None
        for attempt in range(3):
            if rimanente() <= 2.0:
                log.info("Coach: budget di tempo esaurito dopo %d tentativi", i + attempt)
                raise last_error or TimeoutError(
                    f"nessuna risposta utilizzabile entro {timeout:.0f}s"
                )
            try:
                data = _post_json(
                    f"{base_url}/chat/completions", payload, api_key, rimanente()
                )
                break
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", "replace")[:300]
                # Un 429 puo' voler dire due cose opposte: troppe richieste al
                # secondo (passa da solo) oppure quota esaurita (non passa fino
                # al rinnovo). Ritentare la seconda e' tempo buttato.
                quota_finita = exc.code == 429 and "quota" in body.lower()
                if quota_finita:
                    raise RuntimeError(
                        "Quota del provider esaurita. Aspetta il rinnovo, prova un altro "
                        "modello con --list-models, oppure passa a un'altra chiave."
                    ) from exc
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
        parsed = _parse_json_loose(text)
        if parsed is None:
            if i < len(attempts) - 1:
                log.info("Coach: risposta non JSON, riprovo con un vincolo piu' stretto")
                continue
            log.error("Coach: risposta non interpretabile: %r", text[:200])
            raise json.JSONDecodeError("nessun JSON nella risposta", text or "", 0)
        usage = data.get("usage") or {}
        log.info(
            "Coach: %s (%s) in=%s out=%s",
            model, base_url,
            usage.get("prompt_tokens", "?"), usage.get("completion_tokens", "?"),
        )
        parsed["usage"] = {
            "in": usage.get("prompt_tokens"),
            "out": usage.get("completion_tokens"),
            "modello": model,
        }
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
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Report di coaching. Usa Claude se c'e' una API key, altrimenti l'euristica locale.

    history: giri precedenti sulla stessa pista, cosi' il coach vede la progressione
    invece di ripartire da zero a ogni giro.
    profile: come guida abitualmente il pilota, per distinguere l'episodio dal vizio.
    """
    if force_heuristic:
        return _heuristic_report(analysis)

    # Backend generico (Google AI Studio, OpenRouter, Groq, Ollama...): se
    # COACH_BASE_URL e' configurato ha la precedenza su Anthropic.
    if os.getenv("COACH_BASE_URL", "").strip():
        try:
            parsed = _openai_compat_report(analysis, history, profile)
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
        compact = _compact_analysis(analysis, history, profile)

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
        parsed["usage"] = {
            "in": message.usage.input_tokens,
            "out": message.usage.output_tokens,
            "cache_read": message.usage.cache_read_input_tokens or 0,
            "modello": message.model,
        }

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
