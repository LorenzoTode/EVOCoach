"""Diario di bordo della sessione: una riga per evento, dal via alla chiusura.

Il log a rotazione conserva le ultime righe; questo conserva la sessione
intera. Sono due cose diverse: il primo serve a capire un errore, il secondo a
ricostruire cosa e' successo davvero — quali giri, in che ordine, con che
esito, e cosa ha risposto il coach a ognuno.

Formato JSONL: una riga per evento, scritta e chiusa subito. Se il gioco si
pianta o l'app viene chiusa a metà, quello che era gia' successo resta.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from storage.paths import app_dir

log = logging.getLogger(__name__)


def sessions_dir() -> Path:
    return app_dir() / "data" / "sessions"


def _slug(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "sconosciuta").lower()).strip("-") or "sconosciuta"


class SessionJournal:
    """Scrive gli eventi di una sessione. Silenzioso se il disco fa i capricci:
    un diario che non si puo' scrivere non deve impedire di guidare."""

    def __init__(self) -> None:
        self.path: Path | None = None
        self._started: float | None = None
        self._counts: dict[str, int] = {}

    def start(self, track: str | None, car: str | None, **extra: Any) -> None:
        self.close()
        self._started = time.time()
        self._counts = {}
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(self._started))
        try:
            sessions_dir().mkdir(parents=True, exist_ok=True)
            self.path = sessions_dir() / f"{stamp}-{_slug(track)}.jsonl"
        except OSError as exc:
            log.warning("Diario non apribile: %s", exc)
            self.path = None
            return
        self.event("session_start", track=track, car=car, **extra)

    def event(self, kind: str, **data: Any) -> None:
        self._counts[kind] = self._counts.get(kind, 0) + 1
        if not self.path:
            return
        row = {
            "t": round(time.time(), 3),
            "dt": round(time.time() - (self._started or time.time()), 1),
            "kind": kind,
            **data,
        }
        try:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        except (OSError, TypeError) as exc:
            log.warning("Evento %s non scritto nel diario: %s", kind, exc)

    def close(self) -> None:
        if self.path and self._started:
            self.event("session_end", durata_s=round(time.time() - self._started), eventi=dict(self._counts))
        self.path = None

    # ---- lettura ---------------------------------------------------------

    def read(self, path: Path | None = None) -> list[dict[str, Any]]:
        target = path or self.path
        if not target or not target.is_file():
            return []
        rows = []
        for line in target.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                rows.append({"kind": "riga_illeggibile", "raw": line[:200]})
        return rows

    def read_current_or_last(self) -> tuple[list[dict[str, Any]], str | None]:
        """Il diario in corso, oppure l'ultimo chiuso.

        A sessione finita self.path e' None, ma il file resta: chi esporta
        dopo aver spento il gioco vuole comunque vedere cosa e' successo.
        """
        if self.path:
            return self.read(), self.path.name
        try:
            files = sorted(sessions_dir().glob("*.jsonl"), reverse=True)
        except OSError:
            return [], None
        if not files:
            return [], None
        return self.read(files[0]), files[0].name

    @staticmethod
    def list_sessions(limit: int = 30) -> list[dict[str, Any]]:
        try:
            files = sorted(sessions_dir().glob("*.jsonl"), reverse=True)[:limit]
        except OSError:
            return []
        return [
            {"file": f.name, "kb": round(f.stat().st_size / 1024, 1), "modificato": f.stat().st_mtime}
            for f in files
        ]
