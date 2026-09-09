"""Cosa e' gia' stato consigliato, e cosa e' successo dopo.

Un coach che a ogni giro ricalcola da zero dice ogni volta la stessa cosa: le
abitudini cambiano in settimane, le mediane in dieci giri, e l'analisi del
giro appena chiuso somiglia moltissimo a quella del giro prima. Il risultato e'
un consiglio che sembra nuovo e non lo e', e che dopo tre volte si smette di
leggere.

Qui si tiene il filo: quale modifica e' stata proposta, se il pilota l'ha fatta
davvero — lo si legge dall'elettronica, non glielo si chiede — e come si e'
mossa la metrica che quella modifica doveva spostare. Da li' il consiglio
successivo non ripete: verifica, giudica, e propone altro solo quando ha visto
l'effetto del cambio precedente.
"""

from __future__ import annotations

from typing import Any

# Ogni parametro sa quale metrica dovrebbe muovere e in che direzione, cosi'
# l'esito e' misurabile invece che opinabile. "rumore" e' quanto la metrica
# balla da sola fra due giri: sotto quella soglia non e' successo niente.
PARAMETRI: tuple[dict[str, Any], ...] = (
    {
        "nome": "ABS",
        "key": "abs_level",
        "alias": ("abs", "antibloccaggio", "anti-lock"),
        "metrica": "overlap_pct",
        "meglio": "giu",
        "rumore": 0.8,
    },
    {
        "nome": "TC",
        "key": "tc_level",
        "alias": ("tc", "traction control", "controllo di trazione", "trazione"),
        "metrica": "max_slip",
        "meglio": "giu",
        "rumore": 0.03,
    },
    {
        "nome": "Diff Power",
        "key": "diff_power",
        "alias": ("diff power", "differenziale", "diff", "power"),
        "metrica": "early_throttle_pct",
        "meglio": "giu",
        "rumore": 6.0,
    },
    {
        "nome": "Brake Bias",
        "key": "brake_bias",
        "alias": ("brake bias", "bias", "ripartizione"),
        "metrica": "brake_peak",
        "meglio": "giu",
        "rumore": 0.03,
    },
    {
        "nome": "Engine Brake",
        "key": "engine_brake",
        "alias": ("engine brake", "freno motore"),
        "metrica": None,
        "meglio": None,
        "rumore": 0.0,
    },
)

# Oltre questo numero di proposte ignorate si smette di insistere: se dopo tre
# volte quella modifica non e' stata fatta, non e' una dimenticanza.
LIMITE_INSISTENZA = 3


def _num(value: Any) -> float | None:
    """Numero da un campo che puo' arrivare come stringa formattata."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        pulito = value.strip().replace(",", ".").replace("%", "")
        try:
            return float(pulito)
        except ValueError:
            return None
    return None


def resolve_parameter(nome: Any) -> dict[str, Any] | None:
    """Dal nome scritto nel consiglio al parametro dell'elettronica.

    Il modello scrive "Traction Control", "TC" o "controllo di trazione" a
    seconda dell'umore: senza questa normalizzazione ogni variante sembra un
    parametro diverso e il consiglio ripetuto passa inosservato.
    """
    testo = str(nome or "").strip().lower()
    if not testo:
        return None
    for spec in PARAMETRI:
        if testo == spec["nome"].lower() or any(a == testo for a in spec["alias"]):
            return spec
    for spec in PARAMETRI:
        if any(a in testo for a in spec["alias"]):
            return spec
    return None


def _fmt(value: Any) -> str:
    """2.0 letto dal gioco si scrive "2": e' un livello di ABS, non una misura."""
    numero = _num(value)
    if numero is None:
        return str(value)
    return f"{numero:g}"


def _valore_attuale(electronics: dict[str, Any], key: str) -> float | None:
    return _num((electronics or {}).get(f"electronics_{key}"))


def _stato_modifica(
    voce: dict[str, Any], spec: dict[str, Any], electronics: dict[str, Any]
) -> tuple[str, float | None]:
    """La modifica proposta e' stata fatta? Lo dice il gioco, non il pilota."""
    ora = _valore_attuale(electronics, spec["key"])
    da, a = _num(voce.get("current")), _num(voce.get("target"))
    if ora is None or a is None:
        return "sconosciuto", ora
    if abs(ora - a) < 1e-6:
        return "applicato", ora
    if da is not None and abs(ora - da) < 1e-6:
        return "non_applicato", ora
    return "cambiato_altrimenti", ora


def _giudizio(spec: dict[str, Any], prima: float | None, dopo: float | None) -> str:
    if prima is None or dopo is None:
        return "non_misurabile"
    variazione = dopo - prima
    if abs(variazione) < spec["rumore"]:
        return "invariato"
    migliora = variazione < 0 if spec["meglio"] == "giu" else variazione > 0
    return "migliorato" if migliora else "peggiorato"


def build_history_block(
    records: list[dict[str, Any]],
    electronics: dict[str, Any],
    metrics: dict[str, Any],
    *,
    lap_time_ms: int | None = None,
) -> dict[str, Any]:
    """Lo storico dei consigli in forma leggibile dal modello.

    records: i report precedenti dello stesso pilota sulla stessa pista, dal
    piu' recente. electronics e metrics sono quelli di ADESSO: il confronto fra
    cosa fu proposto e cosa si legge oggi e' tutta la sostanza.
    """
    if not records:
        return {}

    proposte: dict[str, dict[str, Any]] = {}
    esiti: list[dict[str, Any]] = []
    detti: list[str] = []

    for indice, rec in enumerate(records):
        if rec.get("summary"):
            detti.append(str(rec["summary"]))
        for voce in rec.get("setup") or []:
            spec = resolve_parameter(voce.get("parameter"))
            if not spec:
                continue
            stato, ora = _stato_modifica(voce, spec, electronics)
            slot = proposte.setdefault(
                spec["nome"],
                {
                    "parametro": spec["nome"],
                    "volte": 0,
                    "da": voce.get("current"),
                    "a": voce.get("target"),
                    "perche": voce.get("because"),
                    "report_fa": indice,
                    "stato": stato,
                    "valore_ora": ora,
                },
            )
            slot["volte"] += 1
            # Il piu' recente comanda: e' quello che il pilota ha letto per ultimo.
            if indice < slot["report_fa"]:
                slot.update(
                    {"da": voce.get("current"), "a": voce.get("target"),
                     "perche": voce.get("because"), "report_fa": indice,
                     "stato": stato, "valore_ora": ora}
                )

            # L'esito si misura solo sul consiglio piu' recente per quel
            # parametro, e solo se e' stato applicato: altrimenti si
            # attribuirebbe a una modifica mai fatta il merito di un caso.
            if indice == 0 and stato == "applicato" and spec["metrica"]:
                prima = _num((rec.get("metrics") or {}).get(spec["metrica"]))
                dopo = _num((metrics or {}).get(spec["metrica"]))
                esiti.append(
                    {
                        "parametro": spec["nome"],
                        "modifica": f"{voce.get('current')} -> {voce.get('target')}",
                        "metrica": spec["metrica"],
                        "prima": prima,
                        "dopo": dopo,
                        "variazione": None if prima is None or dopo is None else round(dopo - prima, 3),
                        "giudizio": _giudizio(spec, prima, dopo),
                        "nota": "correlazione, non prova di causa",
                    }
                )

    ultimo = records[0]
    blocco: dict[str, Any] = {
        "report_precedenti": len(records),
        "consigli_precedenti": sorted(
            proposte.values(), key=lambda v: (v["report_fa"], v["parametro"])
        ),
        "esiti_misurati": esiti,
        "in_sospeso": [v["parametro"] for v in proposte.values() if v["stato"] == "non_applicato"],
        "gia_detto": detti[:3],
        "tempo": {
            "quando_consigliato_ms": ultimo.get("lap_time_ms"),
            "adesso_ms": lap_time_ms,
            "differenza_ms": (
                None
                if not ultimo.get("lap_time_ms") or not lap_time_ms
                else int(lap_time_ms - ultimo["lap_time_ms"])
            ),
        },
    }
    return blocco


def _ordina(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Una modifica per volta, e detto a chiare lettere quale.

    Cambiare tre cose insieme e leggere il giro dopo non misura niente: se il
    tempo scende non si sa quale delle tre l'ha fatto scendere, e se sale non
    si sa quale tornare indietro. Le altre restano scritte, in coda.
    """
    return [
        {**voce, "azione_ora": i == 0, "in_coda": i > 0}
        for i, voce in enumerate(items)
    ]


def filter_repeats(
    setup_items: list[dict[str, Any]], storico: dict[str, Any]
) -> list[dict[str, Any]]:
    """Toglie dalle proposte cio' che e' gia' stato detto e non e' stato fatto.

    Non lo cancella: lo trasforma in una voce che dice "questo e' ancora in
    sospeso", una volta sola. Ripresentare la stessa modifica come nuova a ogni
    giro e' il modo piu' rapido per far smettere di leggere i consigli; farla
    sparire senza dire niente e' peggio, perche' sembra che non servisse piu'.

    L'ordine che ne esce non e' per gravita' ma per misurabilita': prima si
    corregge cio' che e' stato cambiato e ha peggiorato, poi si applica cio'
    che era gia' stato chiesto, e solo dopo si aggiunge qualcosa di nuovo.
    """
    if not storico:
        return _ordina(setup_items)

    per_nome = {v["parametro"]: v for v in storico.get("consigli_precedenti", [])}
    esiti = {e["parametro"]: e for e in storico.get("esiti_misurati", [])}
    ritorni: list[dict[str, Any]] = []
    sospesi: list[dict[str, Any]] = []
    nuovi: list[dict[str, Any]] = []
    visti: set[str] = set()

    for voce in setup_items:
        spec = resolve_parameter(voce.get("parameter"))
        nome = spec["nome"] if spec else str(voce.get("parameter") or "")
        if nome in visti:
            continue
        visti.add(nome)
        precedente = per_nome.get(nome)
        esito = esiti.get(nome)

        # Applicato e ha funzionato: non si tocca piu'. Insistere sullo stesso
        # parametro mentre sta dando i suoi effetti confonde le due cose.
        if esito and esito["giudizio"] == "migliorato":
            continue

        # Applicato e ha peggiorato: la proposta e' tornare indietro, non
        # spingere oltre nella stessa direzione.
        if esito and esito["giudizio"] == "peggiorato":
            da, a = esito["modifica"].split(" -> ")[0], esito["modifica"].split(" -> ")[-1]
            ritorni.append(
                {
                    **voce,
                    "severity": "medium",
                    "title": f"Torna indietro su {nome}",
                    "current": a,
                    "target": da,
                    "action": f"Riporta {nome} a {da}",
                    "detail": (
                        f"Dopo il cambio {esito['modifica']} la metrica {esito['metrica']} e' passata "
                        f"da {esito['prima']} a {esito['dopo']}: la direzione era sbagliata."
                    ),
                    "because": "Misurato sul giro dopo la modifica, non ipotizzato.",
                    "dallo_storico": True,
                    "esito": esito,
                }
            )
            continue

        if precedente and precedente["stato"] == "non_applicato":
            volte = precedente["volte"]
            if volte >= LIMITE_INSISTENZA:
                # Tre volte ignorata non e' una dimenticanza: si prende atto e
                # si smette, lasciando la traccia senza urlare.
                sospesi.append(
                    {
                        **voce,
                        "severity": "low",
                        "title": f"{nome} {precedente['da']} -> {precedente['a']} (non fatta)",
                        "detail": (
                            f"Proposta {volte} volte e mai applicata: l'elettronica dice ancora "
                            f"{_fmt(precedente['valore_ora'])}. Se non vuoi cambiarla va bene, "
                            f"ma allora il sintomo resta e si lavora solo di tecnica."
                        ),
                        "dallo_storico": True,
                        "in_sospeso": True,
                        "volte": volte,
                    }
                )
            else:
                sospesi.append(
                    {
                        **voce,
                        "title": f"Ancora da fare: {nome} {precedente['da']} -> {precedente['a']}",
                        "detail": (
                            f"Gia' consigliata e non ancora applicata: il gioco riporta "
                            f"{_fmt(precedente['valore_ora'])}. Finche' resta com'e' non si puo' "
                            f"sapere se serviva."
                        ),
                        "dallo_storico": True,
                        "in_sospeso": True,
                        "volte": volte,
                    }
                )
            continue

        nuovi.append(voce)

    # Le proposte gia' pendenti si contano una volta sola: quattro cartelli
    # "ancora da fare" sono quattro modi di dire la stessa cosa. Quella che
    # resta a schermo nomina le altre.
    if len(sospesi) > 1:
        primo, resto = sospesi[0], sospesi[1:]
        altri = ", ".join(
            str(v.get("parameter") or v.get("title")) for v in resto
        )
        primo = {
            **primo,
            "detail": f"{primo['detail']} In coda dopo questa: {altri}.",
            "altri_in_sospeso": [v.get("parameter") for v in resto],
        }
        sospesi = [primo]

    return _ordina(ritorni + sospesi + nuovi)
