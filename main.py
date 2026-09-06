"""ACEVO Telemetry Coach — web UI + live analysis server."""

from __future__ import annotations

import argparse
import sys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ACEVO Telemetry Coach")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument(
        "--mode",
        choices=("auto", "demo", "live"),
        default="auto",
        help="auto: live if game is up else demo. demo: always synthetic. live: shared memory only.",
    )
    parser.add_argument("--hz", type=float, default=15.0)
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="List the models the configured coach backend can actually use, then exit.",
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Legacy console telemetry monitor instead of the web app.",
    )
    return parser.parse_args()


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


def main() -> int:
    args = parse_args()
    if args.list_models:
        return list_models()
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

    uvicorn.run("server.app:app", host=args.host, port=args.port, reload=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
