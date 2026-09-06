"""Impacchetta ACEVO Coach in un singolo eseguibile Windows.

    python -m pip install pyinstaller
    python build_exe.py

Produce dist/ACEVOCoach.exe. Va lanciato su Windows: PyInstaller non fa
compilazione incrociata, un eseguibile Windows si costruisce su Windows.

Il file .env NON viene incluso: resta accanto all'eseguibile, cosi' la chiave
API non finisce dentro un binario che potresti passare a qualcuno.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SEP = ";" if sys.platform == "win32" else ":"

# uvicorn sceglie le sue implementazioni a runtime, quindi PyInstaller non le
# vede analizzando gli import: vanno dichiarate a mano.
HIDDEN = [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "websockets",
    "websockets.legacy",
    "anyio._backends._asyncio",
]


def main() -> int:
    dist = ROOT / "web" / "dist"
    if not (dist / "index.html").exists():
        print("web/dist non c'e'. Costruisci prima il frontend:", file=sys.stderr)
        print("    cd web && npm install && npm run build", file=sys.stderr)
        return 1

    try:
        import PyInstaller.__main__
    except ImportError:
        print("PyInstaller non installato:  python -m pip install pyinstaller", file=sys.stderr)
        return 1

    for stale in ("build", "dist/ACEVOCoach", "ACEVOCoach.spec"):
        target = ROOT / stale
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        elif target.exists():
            target.unlink()

    args = [
        str(ROOT / "main.py"),
        "--name", "ACEVOCoach",
        "--onefile",
        "--console",
        "--noconfirm",
        "--add-data", f"{dist}{SEP}web/dist",
        "--collect-all", "acevo",
    ]
    for mod in HIDDEN:
        args += ["--hidden-import", mod]

    PyInstaller.__main__.run(args)

    exe = ROOT / "dist" / ("ACEVOCoach.exe" if sys.platform == "win32" else "ACEVOCoach")
    if exe.exists():
        print(f"\n  Fatto: {exe}")
        print("  Mettilo accanto al file .env e fai doppio clic.\n")
        return 0
    print("\n  Build finita ma l'eseguibile non si trova in dist/.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
