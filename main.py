"""ACEVO Telemetry Coach — web UI + live analysis server."""

from __future__ import annotations

import argparse
import sys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ACEVO Telemetry Coach")
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help=(
            "Interfaccia di ascolto. Default 0.0.0.0: raggiungibile dalla rete "
            "locale, che e' il caso d'uso normale (il gioco su un PC, "
            "l'interfaccia su un altro schermo). Usa 127.0.0.1 per limitarlo "
            "a questo computer."
        ),
    )
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument(
        "--mode",
        choices=("auto", "demo", "live"),
        default="live",
        help=(
            "live (default): waits for AC EVO, starts with no data. "
            "demo: synthetic Monza lap, for trying the app without the game. "
            "auto: live if the game is up, else demo."
        ),
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open the browser on start.",
    )
    parser.add_argument("--hz", type=float, default=15.0)
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="List the models the configured coach backend can actually use, then exit.",
    )
    parser.add_argument(
        "--export",
        metavar="FILE",
        nargs="?",
        const="",
        help="Scrive un file di diagnostica (giri, profili, log) ed esce.",
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Legacy console telemetry monitor instead of the web app.",
    )
    return parser.parse_args()


def lan_ip() -> str | None:
    """Indirizzo di questo PC sulla rete locale.

    Aprire un socket UDP verso un indirizzo esterno non invia nulla: serve
    solo a farsi dire dal sistema operativo quale interfaccia userebbe.
    """
    import socket

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 80))
            return str(sock.getsockname()[0])
        finally:
            sock.close()
    except OSError:
        return None


def list_models() -> int:
    """Chiede al provider quali modelli sono disponibili con la chiave configurata.

    I nomi dei modelli cambiano spesso e un nome ritirato da' un 404: meglio
    chiederli che tenerli scritti in una guida che invecchia.
    """
    import json
    import os
    import urllib.error
    import urllib.request

    from dotenv import load_dotenv

    load_dotenv()
    base_url = os.getenv("COACH_BASE_URL", "").strip().rstrip("/")

    if base_url:
        key = os.getenv("COACH_API_KEY", "").strip()
        req = urllib.request.Request(
            f"{base_url}/models", headers={"Authorization": f"Bearer {key}"}
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            print(f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:400]}", file=sys.stderr)
            return 1
        except urllib.error.URLError as exc:
            print(f"Provider irraggiungibile: {exc.reason}", file=sys.stderr)
            return 1
        names = sorted(m.get("id", "?") for m in data.get("data", []))
        # Euristica sui nomi: i cataloghi mescolano modelli di testo con
        # immagini, audio e video, che qui non servono. Non li nascondo,
        # li metto in fondo — la regola e' un'ipotesi, non una garanzia.
        other_hints = (
            "image", "tts", "audio", "video", "embedding", "transcribe",
            "live", "robotics", "lyria", "veo", "banana", "computer-use", "aqa",
        )
        text = [n for n in names if not any(h in n for h in other_hints)]
        other = [n for n in names if n not in text]

        print(f"Modelli su {base_url} ({len(names)} in totale)\n")
        print("Adatti al coach (testo):\n")
        for name in text:
            alias = "   <- alias, non invecchia" if name.endswith("-latest") else ""
            print(f"  COACH_MODEL={name}{alias}")
        if other:
            print(f"\nProbabilmente non adatti — immagini, audio, video, embedding ({len(other)}):\n")
            print("  " + ", ".join(n.removeprefix("models/") for n in other))
        return 0

    if os.getenv("ANTHROPIC_API_KEY", "").strip():
        import anthropic

        print("Modelli disponibili su Anthropic:\n")
        for model in anthropic.Anthropic().models.list():
            print(f"  ANTHROPIC_MODEL={model.id}   ({model.display_name})")
        return 0

    print(
        "Nessun backend configurato: imposta COACH_BASE_URL oppure "
        "ANTHROPIC_API_KEY nel file .env (vedi .env.example).",
        file=sys.stderr,
    )
    return 1


def export_diagnostics(target: str) -> int:
    """Esporta la diagnostica senza avviare il server."""
    import json
    from pathlib import Path

    from server.app import _build_export
    from storage.paths import app_dir

    payload = _build_export()
    path = Path(target) if target else (
        app_dir() / f"acevo-coach-{payload['installazione']}.json"
    )
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    size = path.stat().st_size / 1024
    print(f"\n  Scritto: {path}  ({size:.0f} KB)")
    print(f"  Giri: {len(payload['giri'])} · piste: {', '.join(payload['piste']) or 'nessuna'}")
    print("  Non contiene la chiave API ne' percorsi del disco.\n")
    return 0


def main() -> int:
    args = parse_args()
    if args.list_models:
        return list_models()
    if args.export is not None:
        return export_diagnostics(args.export)
    if args.cli:
        from telemetry.live import LiveSharedMemoryClient

        client = LiveSharedMemoryClient()
        client.run_forever(hz=args.hz)
        return 0

    import os

    os.environ["ACEVO_MODE"] = args.mode
    os.environ["TELEMETRY_HZ"] = str(args.hz)

    try:
        import uvicorn
    except ImportError:
        print("Install deps: python -m pip install -r requirements.txt", file=sys.stderr)
        return 1

    # Con --host 0.0.0.0 il server ascolta ovunque, ma la finestra locale deve
    # puntare a un indirizzo concreto.
    local = "127.0.0.1" if args.host in ("0.0.0.0", "::", "") else args.host
    url = f"http://{local}:{args.port}"

    print("\n  ACEVO COACH")
    print(f"    su questo PC     {url}")
    if args.host in ("0.0.0.0", "::", ""):
        ip = lan_ip()
        if ip:
            print(f"    da un altro schermo  http://{ip}:{args.port}")
            print("    (stessa rete; serve la regola del firewall sulla porta %d)" % args.port)
        else:
            print("    da un altro schermo  http://<ip-di-questo-pc>:%d" % args.port)
    print()

    if not args.no_browser:
        import threading
        import webbrowser

        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    # L'oggetto invece della stringa "server.app:app": una stringa d'import
    # non si risolve dentro un eseguibile impacchettato.
    from server.app import app as fastapi_app

    uvicorn.run(fastapi_app, host=args.host, port=args.port, reload=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
