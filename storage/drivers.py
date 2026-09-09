"""Chi sta guidando: due profili distinti sulla stessa macchina.

Lo stesso gioco, lo stesso computer, due persone diverse. Senza questa
distinzione i giri finiscono tutti nello stesso mucchio e il profilo di guida
diventa la media di due piloti — cioe' nessuno dei due, e un coach che parla
di un'abitudine che ne' l'uno ne' l'altro ha davvero.

Il registro e' un file JSON accanto al database. Piccolo di proposito: chi
guida e' un'informazione che deve sopravvivere a un riavvio, non un archivio.
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

# I giri gia' archiviati prima che esistessero i profili appartengono a chi
# usava l'app fino a ieri: il primo pilota. Cambiare questo valore vorrebbe
# dire orfanare tutto lo storico.
DEFAULT_DRIVER = "p1"

SEED: tuple[dict[str, str], ...] = (
    {"id": "p1", "nome": "Pilota 1"},
    {"id": "p2", "nome": "Pilota 2"},
)


def registry_path() -> Path:
    return app_dir() / "data" / "drivers.json"


def _slug(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-") or "pilota"


class DriverRegistry:
    """Elenco dei piloti e chi e' al volante adesso.

    Scrive a ogni modifica: se l'app si chiude di colpo, chi stava guidando
    resta quello giusto al riavvio successivo.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path or registry_path())
        self._data: dict[str, Any] = {"attivo": DEFAULT_DRIVER, "piloti": []}
        self._load()

    # ---- persistenza -----------------------------------------------------

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}

        piloti = [p for p in (raw.get("piloti") or []) if isinstance(p, dict) and p.get("id")]
        esistenti = {p["id"] for p in piloti}
        for seme in SEED:
            if seme["id"] not in esistenti:
                piloti.append({**seme, "creato": time.time()})
        self._data["piloti"] = piloti

        attivo = raw.get("attivo")
        self._data["attivo"] = attivo if any(p["id"] == attivo for p in piloti) else DEFAULT_DRIVER
        if raw.get("attivo") != self._data["attivo"] or len(piloti) != len(raw.get("piloti") or []):
            self._save()

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=1), encoding="utf-8"
            )
        except OSError as exc:
            log.warning("Registro piloti non salvato: %s", exc)

    # ---- lettura ---------------------------------------------------------

    @property
    def active(self) -> str:
        return str(self._data["attivo"])

    def exists(self, driver_id: str | None) -> bool:
        return any(p["id"] == driver_id for p in self._data["piloti"])

    def name(self, driver_id: str | None = None) -> str:
        target = driver_id or self.active
        for p in self._data["piloti"]:
            if p["id"] == target:
                return str(p.get("nome") or target)
        return str(target)

    def slug(self, driver_id: str | None = None) -> str:
        return _slug(self.name(driver_id))

    def ids(self) -> list[str]:
        return [str(p["id"]) for p in self._data["piloti"]]

    def list(self) -> list[dict[str, Any]]:
        return [
            {"id": p["id"], "nome": p.get("nome") or p["id"], "attivo": p["id"] == self.active}
            for p in self._data["piloti"]
        ]

    # ---- modifica --------------------------------------------------------

    def switch(self, driver_id: str) -> bool:
        """True se il pilota e' cambiato davvero. False se non esiste o era gia' lui."""
        if not self.exists(driver_id) or driver_id == self.active:
            return False
        self._data["attivo"] = driver_id
        self._save()
        return True

    def rename(self, driver_id: str, nome: str) -> bool:
        nome = (nome or "").strip()[:40]
        if not nome or not self.exists(driver_id):
            return False
        for p in self._data["piloti"]:
            if p["id"] == driver_id:
                p["nome"] = nome
        self._save()
        return True
