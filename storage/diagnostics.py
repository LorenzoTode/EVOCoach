"""Log su file ed esportazione della sessione.

Serve a due cose diverse. La prima: quando qualcosa non torna, poter mandare
un file solo invece di descrivere a parole cosa si e' visto. La seconda:
raccogliere il profilo di piu' piloti in modo confrontabile.

Cosa NON entra mai nell'esportazione: la chiave API, il contenuto del .env,
i percorsi del disco, il nome utente. Un file di diagnostica si manda in giro,
e va scritto sapendolo.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import platform
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from storage.paths import app_dir

LOG_LINES_IN_EXPORT = 400


def log_path() -> Path:
    return app_dir() / "data" / "acevo-coach.log"


def setup_logging(level: int = logging.INFO) -> Path:
    """Log a rotazione su file, oltre alla console.

    Due file da 1 MB bastano per una serata di prove e non crescono all'infinito.
    """
    target = log_path()
    target.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(level)
    if any(isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers):
        return target

    handler = logging.handlers.RotatingFileHandler(
        target, maxBytes=1_000_000, backupCount=1, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)-22s %(message)s")
    )
    root.addHandler(handler)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    return target


def install_id() -> str:
    """Identificativo casuale dell'installazione, generato una volta.

    Non contiene nulla della macchina ne' della persona: serve solo a non
    confondere fra loro i profili di piloti diversi.
    """
    marker = app_dir() / "data" / "install.json"
    try:
        if marker.is_file():
            value = json.loads(marker.read_text(encoding="utf-8")).get("install_id")
            if value:
                return str(value)
    except (OSError, ValueError):
        pass

    value = uuid.uuid4().hex[:12]
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({"install_id": value}), encoding="utf-8")
    except OSError:
        pass
    return value


def app_version() -> str:
    """Versione = commit del repo, se disponibile; altrimenti sconosciuta.

    Legare i dati raccolti alla versione che li ha prodotti evita di
    confrontare profili calcolati con formule diverse.
    """
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=app_dir(), capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "sconosciuta"


def tail_log(lines: int = LOG_LINES_IN_EXPORT) -> list[str]:
    try:
        content = log_path().read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return content.splitlines()[-lines:]
