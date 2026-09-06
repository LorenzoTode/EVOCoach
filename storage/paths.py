"""Dove stanno i file che l'app scrive e legge a runtime.

Impacchettata con PyInstaller la distinzione e' vitale: __file__ punta nella
cartella temporanea di estrazione, che Windows cancella quando l'app si chiude.
Il codice puo' stare li', i dati no — o a ogni chiusura si perdono i giri.
"""

from __future__ import annotations

import sys
from pathlib import Path


def app_dir() -> Path:
    """Cartella persistente accanto all'eseguibile (o alla radice del sorgente).

    Qui vivono il file .env e la cartella data/.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def bundle_dir() -> Path:
    """Cartella dei file inclusi nel pacchetto, come web/dist.

    Sotto PyInstaller e' temporanea: va bene per la sola lettura.
    """
    bundle = getattr(sys, "_MEIPASS", None)
    return Path(bundle) if bundle else Path(__file__).resolve().parent.parent
