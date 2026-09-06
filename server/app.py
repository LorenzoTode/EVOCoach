"""FastAPI app: live telemetry WS, analysis, coaching, static UI."""

from __future__ import annotations

import asyncio
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from analysis.delta import build_analysis_payload
from analysis.setup_acevo import build_acevo_setup_instructions
from coach.report import generate_coach_report
from storage.db import Database
from storage.paths import app_dir, bundle_dir
from telemetry.demo import DemoPlayer, MONZA_CORNERS
from telemetry.track_map import TrackMapBuilder

# find_dotenv() risalirebbe da __file__, che impacchettato e' la cartella
# temporanea: il .env accanto all'eseguibile non verrebbe mai trovato.
_ENV_FILE = app_dir() / ".env"
load_dotenv(_ENV_FILE if _ENV_FILE.exists() else None)

ROOT = bundle_dir()
WEB_DIST = ROOT / "web" / "dist"
HZ = float(os.getenv("TELEMETRY_HZ", "15"))

# Sotto questa soglia non e' un giro: reset in pista, teletrasporto ai box,
# cambio sessione. Il gioco puo' comunque emettere un "last lap time".
MIN_LAP_MS = 15_000

ELECTRONICS_KEYS = (
    "electronics_tc_level",
    "electronics_tc_level_min",
    "electronics_tc_level_max",
    "electronics_abs_level",
    "electronics_abs_level_min",
    "electronics_abs_level_max",
    "electronics_brake_bias",
    "electronics_brake_bias_min",
    "electronics_brake_bias_max",
    "electronics_diff_power",
    "electronics_diff_power_min",
    "electronics_diff_power_max",
    "electronics_diff_coast",
    "electronics_diff_coast_min",
    "electronics_diff_coast_max",
    "electronics_engine_map",
    "electronics_front_bump_damper",
    "electronics_front_rebound_damper",
    "electronics_rear_bump_damper",
    "electronics_rear_rebound_damper",
    "electronics_perf_mode",
)


def _track_corners(track: str | None) -> list[dict[str, Any]]:
    if not track:
        return MONZA_CORNERS
    try:
        from acevo.catalogs.tracks import select_track_profile

        _key, profile = select_track_profile(track_name=track)
        if profile and profile.get("corners"):
            return profile["corners"]
    except Exception:
        pass
    return MONZA_CORNERS


def _world_xz(physics: dict[str, Any], graphics: dict[str, Any]) -> tuple[float | None, float | None]:
    coords = graphics.get("car_coordinates")
    if isinstance(coords, list) and coords:
        player = graphics.get("player_car_id") or 0
        try:
            player = int(player)
        except Exception:
            player = 0
        if 0 <= player < len(coords):
            c = coords[player]
            if isinstance(c, dict):
                return c.get("x"), c.get("z")
            if hasattr(c, "x"):
                return getattr(c, "x", None), getattr(c, "z", None)
    tcp = physics.get("tyre_contact_point")
    if isinstance(tcp, list) and tcp:
        pts = []
        for p in tcp:
            if isinstance(p, dict) and p.get("x") is not None:
                pts.append((float(p["x"]), float(p.get("z") or 0.0)))
            elif hasattr(p, "x"):
                pts.append((float(p.x), float(getattr(p, "z", 0.0))))
        if pts:
            return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
    return None, None


def _extract_electronics(graphics: dict[str, Any]) -> dict[str, Any]:
    return {k: graphics.get(k) for k in ELECTRONICS_KEYS if graphics.get(k) is not None}


# Cio' che serve per capire perche' il gioco invalida o non conta un giro.
# Esposto da /api/debug/telemetry: e' la differenza fra sapere e indovinare.
DIAG_KEYS = (
    "session_current_lap", "completed_laps", "total_lap_count", "number_of_laps",
    "current_lap_time_ms", "last_laptime_ms", "last_time_ms",
    "best_laptime_ms", "best_time_ms",
    "is_valid_lap", "is_invalid", "timing_is_invalid", "invalid_reasons",
    "number_of_tyres_out", "penalty", "penalty_time",
    "is_in_pit", "is_in_pit_box", "is_in_pit_lane",
    "normalized_car_position", "normalized_position_source",
    "session", "session_name", "session_phase", "status", "status_name",
    "current_sector_index", "sector_count",
)


def _lap_counter(graphics: dict[str, Any]) -> int | None:
    """Numero di giri completati.

    session_current_lap puo' restare fermo a 0 per tutta la sessione (si vede
    negli hotlap in singleplayer), mentre completed_laps incrementa. Si prende
    il primo dei due che si comporta da contatore.
    """
    for key in ("completed_laps", "session_current_lap", "total_lap_count"):
        value = graphics.get(key)
        if isinstance(value, int) and value > 0:
            return value
    completed = graphics.get("completed_laps")
    return completed if isinstance(completed, int) else graphics.get("session_current_lap")


def _lap_invalidated(graphics: dict[str, Any]) -> bool:
    """Il giro in corso e' stato invalidato dal gioco?

    Tre segnali indipendenti letti dalla memoria condivisa di AC EVO:
      is_valid_lap        flag autoritativo del gioco
      timing_is_invalid   flag del sistema di cronometraggio
      number_of_tyres_out quattro ruote fuori = track limits

    Ognuno da solo invalida il giro. Il flag va ricordato per tutto il giro:
    il gioco puo' azzerarlo sul traguardo, ma il giro resta sporco.
    """
    tyres_out = graphics.get("number_of_tyres_out")
    return (
        graphics.get("is_valid_lap") is False
        or bool(graphics.get("timing_is_invalid"))
        or (isinstance(tyres_out, int) and tyres_out >= 4)
    )


def snapshot_to_frame(snapshot: Any) -> dict[str, Any]:
    p = snapshot.physics or {}
    g = snapshot.graphics or {}
    s = snapshot.static or {}
    npos = g.get("normalized_car_position")
    if npos is None:
        npos = p.get("normalized_car_position") or 0.0
    x, z = _world_xz(p, g)
    slip = p.get("wheel_slip") or [None, None, None, None]
    electronics = _extract_electronics(g)
    return {
        "mode": "live",
        "connected": True,
        "track": s.get("track") or g.get("track") or "unknown",
        "car": g.get("car_model") or s.get("car_model") or "unknown",
        "lap": _lap_counter(g),
        "t_ms": g.get("current_lap_time_ms"),
        "best_ms": g.get("best_laptime_ms") or g.get("best_time_ms"),
        "last_ms": g.get("last_laptime_ms") or g.get("last_time_ms"),
        "npos": float(npos or 0.0),
        "speed": p.get("speed_kmh"),
        "gas": p.get("gas"),
        "brake": p.get("brake"),
        "steer": p.get("steer_angle"),
        "rpm": p.get("rpms"),
        "gear": p.get("gear"),
        "x": x,
        "y": 0.0,
        "z": z,
        "delta_ms": g.get("delta_time_ms"),
        "slip": slip if isinstance(slip, list) else [None, None, None, None],
        "electronics": electronics,
        "lap_invalid": _lap_invalidated(g),
        "tyres_out": g.get("number_of_tyres_out"),
        "in_pit": bool(g.get("is_in_pit") or g.get("is_in_pit_lane") or g.get("is_in_pit_box")),
        "session_name": g.get("session_name"),
        "diag": {k: g.get(k) for k in DIAG_KEYS},
        "physics_setup": {
            "brake_bias": p.get("brake_bias"),
            "tyre_core_temp": p.get("tyre_core_temp") or p.get("tyre_temp"),
            "wheels_pressure": p.get("wheels_pressure"),
            "ride_height": p.get("ride_height"),
        },
        "ts": time.time(),
    }


class LiveHub:
    def __init__(self) -> None:
        self.mode = os.getenv("ACEVO_MODE", "auto")  # auto | demo | live
        self.demo = DemoPlayer()
        self.client = None
        self.latest: dict[str, Any] = {"connected": False, "mode": "waiting"}
        self._lap_samples: list[dict[str, Any]] = []
        self._last_lap_no: int | None = None
        self._session_id: int | None = None
        self.db = Database()
        self.track_map = TrackMapBuilder()
        self._last_electronics: dict[str, Any] = {}
        self._last_physics_setup: dict[str, Any] = {}
        self._task: asyncio.Task | None = None
        # Validita' del giro in corso: sticky, si azzera solo a giro nuovo.
        self._lap_valid = True
        self._lap_had_pit = False
        self._valid_laps = 0
        self._invalid_laps = 0
        self._track: str | None = None
        self._last_npos: float | None = None
        self._last_reported_ms: int | None = None
        self._last_diag: dict[str, Any] = {}
        self._last_saved: dict[str, Any] | None = None

    def _ensure_live_client(self):
        if self.client is not None:
            return self.client
        try:
            from telemetry.live import LiveSharedMemoryClient

            self.client = LiveSharedMemoryClient(retry_seconds=1.0)
            return self.client
        except Exception:
            self.client = None
            return None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self.client:
            self.client.close()
        self.db.close()

    async def _loop(self) -> None:
        interval = 1.0 / max(HZ, 1.0)
        while True:
            started = time.perf_counter()
            frame = await asyncio.to_thread(self._poll_once)
            self.latest = frame
            elapsed = time.perf_counter() - started
            await asyncio.sleep(max(0.0, interval - elapsed))

    def _crossed_line(self, frame: dict[str, Any]) -> bool:
        """Il giro si e' appena chiuso?

        Nessuno dei segnali del gioco e' affidabile da solo: in hotlap
        singleplayer il contatore dei giri puo' restare fermo a 0 per tutta la
        sessione. Se ne guardano tre, e ne basta uno.
        """
        npos = frame.get("npos")
        lap = frame.get("lap")
        last_ms = frame.get("last_ms")

        first_frame = self._last_npos is None and self._last_lap_no is None
        crossed = False
        if not first_frame:
            if isinstance(lap, int) and isinstance(self._last_lap_no, int) and lap > self._last_lap_no:
                crossed = True
            # Il gioco pubblica un tempo nuovo: un giro cronometrato e' finito.
            if last_ms and last_ms != self._last_reported_ms:
                crossed = True
            # Traguardo tagliato: la posizione normalizzata torna indietro.
            if npos is not None and self._last_npos is not None and npos + 0.5 < self._last_npos:
                crossed = True

        self._last_npos = npos if npos is not None else self._last_npos
        if isinstance(lap, int):
            self._last_lap_no = lap
        if last_ms:
            self._last_reported_ms = int(last_ms)
        return crossed

    def _attach_map(self, frame: dict[str, Any]) -> dict[str, Any]:
        self._last_diag = frame.pop("diag", None) or self._last_diag
        self.track_map.ingest(frame)
        frame["map"] = self.track_map.snapshot()
        frame["corners"] = _track_corners(frame.get("track"))
        frame["session"] = self.session_state(frame)
        return frame

    def _poll_once(self) -> dict[str, Any]:
        prefer_demo = self.mode == "demo"
        prefer_live = self.mode == "live"

        if not prefer_demo:
            client = self._ensure_live_client()
            if client is not None:
                try:
                    snap = client.poll()
                except Exception:
                    snap = None
                if snap is not None:
                    frame = snapshot_to_frame(snap)
                    self._last_electronics = frame.get("electronics") or {}
                    self._last_physics_setup = frame.get("physics_setup") or {}
                    self._ingest_live(frame)
                    return self._attach_map(frame)

            # In modalita' live non si ripiega MAI sulla demo, nemmeno quando
            # l'SDK non e' caricabile: mostrare un giro sintetico spacciandolo
            # per telemetria vera e' peggio che dire "gioco non rilevato".
            if prefer_live:
                waiting = {
                    "connected": False,
                    "mode": "live",
                    "waiting": True,
                    "sdk_ready": client is not None,
                    "map": self.track_map.snapshot(),
                }
                waiting["session"] = self.session_state(waiting)
                return waiting

        # demo fallback — solo in modalita' auto o demo
        frame = self.demo.next_frame()
        frame["session"] = self.session_state(frame)
        return frame

    def session_state(self, frame: dict[str, Any]) -> dict[str, Any]:
        """Cosa deve mostrare l'interfaccia adesso.

        waiting_game  il gioco non e' in ascolto
        waiting_lap   collegati, ma nessun giro valido ancora completato
        ready         c'e' almeno un giro valido da analizzare
        demo          modalita' dimostrativa, dati sintetici
        """
        if frame.get("mode") == "demo":
            state = "demo"
        elif not frame.get("connected"):
            state = "waiting_game"
        elif self._valid_laps > 0:
            state = "ready"
        else:
            state = "waiting_lap"
        return {
            "state": state,
            "track": frame.get("track"),
            "car": frame.get("car"),
            "lap": frame.get("lap"),
            "valid_laps": self._valid_laps,
            "invalid_laps": self._invalid_laps,
            "current_lap_valid": self._lap_valid,
            "best_ms": frame.get("best_ms"),
            # Perche' l'ultimo giro e' stato scartato: senza questo, "0 giri
            # validi" dopo dieci giri e' un vicolo cieco.
            "last_lap": self._last_saved,
        }

    def _reset_session(self, track: str | None) -> None:
        """Pista cambiata: i conteggi della sessione precedente non valgono piu'."""
        self._track = track
        self._valid_laps = 0
        self._invalid_laps = 0
        self._lap_valid = True
        self._lap_had_pit = False
        self._lap_samples = []
        self._last_lap_no = None
        self._last_npos = None
        self._last_reported_ms = None
        self._last_saved = None
        self._session_id = None

    def _close_lap(self, frame: dict[str, Any]) -> None:
        """Archivia il giro appena chiuso e riparte pulito."""
        samples = self._lap_samples
        self._lap_samples = []
        was_valid, had_pit = self._lap_valid, self._lap_had_pit
        self._lap_valid, self._lap_had_pit = True, False

        if len(samples) < 30:
            return

        positions = [s["npos"] for s in samples if s.get("npos") is not None]
        span = (max(positions) - min(positions)) if positions else 0.0
        lap_time = int(frame.get("last_ms") or samples[-1].get("t_ms") or 0) or None

        # Quattro modi di non essere un giro buono. Ognuno da solo basta.
        reasons = []
        if not was_valid:
            reasons.append("invalidato dal gioco")
        if had_pit:
            reasons.append("passaggio dai box")
        if not lap_time or lap_time < MIN_LAP_MS:
            reasons.append("tempo assente o troppo breve")
        if span < 0.7:
            reasons.append(f"giro parziale (copre il {span * 100:.0f}% del tracciato)")
        valid = not reasons

        if self._session_id is None:
            self._session_id = self.db.create_session(frame.get("track"), frame.get("car"))

        lap_id = self.db.save_lap(
            self._session_id,
            lap_number=self._last_lap_no,
            lap_time_ms=lap_time,
            track=frame.get("track"),
            car=frame.get("car"),
            samples=samples,
            valid=valid,
            meta={
                "electronics": self._last_electronics,
                "physics_setup": self._last_physics_setup,
                "invalid_reasons": reasons,
            },
        )
        if valid:
            self._valid_laps += 1
        else:
            self._invalid_laps += 1
        self._last_saved = {
            "lap_id": lap_id,
            "lap_time_ms": lap_time,
            "valid": valid,
            "reasons": reasons,
            "samples": len(samples),
            "npos_span": round(span, 3),
        }

    def _ingest_live(self, frame: dict[str, Any]) -> None:
        track = frame.get("track")
        if track and self._track and track != self._track:
            self._reset_session(track)
        elif track and not self._track:
            self._track = track

        sample = {
            "t_ms": frame.get("t_ms") or 0,
            "npos": frame.get("npos") or 0.0,
            "speed": frame.get("speed"),
            "gas": frame.get("gas"),
            "brake": frame.get("brake"),
            "steer": frame.get("steer"),
            "rpm": frame.get("rpm"),
            "gear": frame.get("gear"),
            "x": frame.get("x"),
            "y": frame.get("y"),
            "z": frame.get("z"),
            "slip_fl": (frame.get("slip") or [None] * 4)[0],
            "slip_fr": (frame.get("slip") or [None] * 4)[1],
            "slip_rl": (frame.get("slip") or [None] * 4)[2],
            "slip_rr": (frame.get("slip") or [None] * 4)[3],
        }
        if self._session_id is None:
            self._session_id = self.db.create_session(frame.get("track"), frame.get("car"))

        # Un giro sporcato resta sporco fino alla fine, anche se il gioco
        # rialza il flag sul traguardo.
        if frame.get("lap_invalid"):
            self._lap_valid = False
        if frame.get("in_pit"):
            self._lap_had_pit = True

        if self._crossed_line(frame):
            self._close_lap(frame)

        self._lap_samples.append(sample)


hub = LiveHub()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await hub.start()
    yield
    await hub.stop()


app = FastAPI(title="ACEVO Telemetry Coach", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CoachRequest(BaseModel):
    use_demo: bool = True
    lap_id: int | None = None
    reference_lap_id: int | None = None
    force_heuristic: bool = False


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "mode": hub.mode,
        "latest_mode": hub.latest.get("mode"),
        "map": hub.latest.get("map") or hub.track_map.snapshot(),
    }


@app.get("/api/state")
def state() -> dict[str, Any]:
    return hub.latest


@app.get("/api/map")
def current_map() -> dict[str, Any]:
    if hub.latest.get("mode") == "demo":
        return hub.latest.get("map") or {}
    return hub.track_map.snapshot()


@app.get("/api/demo/bundle")
def demo_bundle() -> dict[str, Any]:
    return hub.demo.demo_bundle()


@app.get("/api/laps")
def list_laps(track: str | None = None, include_invalid: bool = False) -> list[dict[str, Any]]:
    """Giri salvati. Di default solo quelli validi: un giro con track limits
    o penalita' non e' un riferimento e non e' analizzabile con senso."""
    laps = hub.db.list_laps(track=track)
    if include_invalid:
        return laps
    return [lap for lap in laps if lap.get("valid")]


@app.get("/api/session")
def session() -> dict[str, Any]:
    return hub.session_state(hub.latest)


@app.get("/api/debug/telemetry")
def debug_telemetry() -> dict[str, Any]:
    """Cosa dice il gioco e cosa ne capisce l'app.

    Serve quando i giri non vengono contati: mette a confronto i campi grezzi
    della memoria condivisa con lo stato interno, senza dover indovinare.
    """
    return {
        "gioco": hub._last_diag,
        "app": {
            "mode": hub.mode,
            "track": hub._track,
            "giro_corrente_valido": hub._lap_valid,
            "giro_passato_dai_box": hub._lap_had_pit,
            "campioni_giro_in_corso": len(hub._lap_samples),
            "ultimo_numero_giro": hub._last_lap_no,
            "ultimo_npos": hub._last_npos,
            "ultimo_tempo_pubblicato": hub._last_reported_ms,
            "giri_validi": hub._valid_laps,
            "giri_scartati": hub._invalid_laps,
        },
        "ultimo_giro_archiviato": hub._last_saved,
        "giri_nel_database": hub.db.list_laps(limit=10),
    }


@app.get("/api/laps/{lap_id}")
def get_lap(lap_id: int) -> dict[str, Any]:
    lap = hub.db.get_lap(lap_id)
    if not lap:
        return {"error": "not_found"}
    return {"lap": lap, "samples": hub.db.get_samples(lap_id)}


@app.get("/api/tracks/corners")
def corners(track: str = "monza") -> dict[str, Any]:
    return {"track": track, "corners": _track_corners(track)}


def _demo_electronics() -> dict[str, Any]:
    return {
        "electronics_tc_level": 3,
        "electronics_tc_level_max": 10,
        "electronics_abs_level": 2,
        "electronics_abs_level_max": 10,
        "electronics_brake_bias": 0.545,
        "electronics_diff_power": 40,
        "electronics_diff_coast": 30,
        "electronics_engine_map": 2,
        "electronics_front_bump_damper": 8,
        "electronics_front_rebound_damper": 10,
        "electronics_rear_bump_damper": 7,
        "electronics_rear_rebound_damper": 9,
    }


def _demo_physics() -> dict[str, Any]:
    return {
        "brake_bias": 0.545,
        "tyre_core_temp": [88.0, 89.0, 96.0, 97.0],
        "wheels_pressure": [27.2, 27.1, 26.8, 26.9],
    }


@app.post("/api/analyze/demo")
def analyze_demo() -> dict[str, Any]:
    bundle = hub.demo.demo_bundle()
    electronics = _demo_electronics()
    physics = _demo_physics()
    analysis = build_analysis_payload(
        bundle["current"],
        bundle["reference"],
        bundle["corners"],
        meta={
            "track": bundle["track"],
            "car": bundle["car"],
            "current_lap_time_ms": bundle["current_lap_time_ms"],
            "reference_lap_time_ms": bundle["reference_lap_time_ms"],
            "electronics": electronics,
        },
        electronics=electronics,
        physics=physics,
    )
    coach = generate_coach_report(analysis)
    return {
        "analysis": analysis,
        "coach": coach,
        "path": bundle["path"],
        "corners": bundle["corners"],
        "reference": bundle["reference"],
        "current": bundle["current"],
        "meta": analysis["meta"],
        "electronics": electronics,
    }


@app.post("/api/coach")
def coach(req: CoachRequest) -> dict[str, Any]:
    if req.use_demo or req.lap_id is None:
        return analyze_demo()

    lap = hub.db.get_lap(req.lap_id)
    if not lap:
        return {"error": "lap_not_found"}
    current = hub.db.get_samples(req.lap_id)
    ref_id = req.reference_lap_id
    if ref_id is None:
        best = hub.db.best_lap(lap.get("track"))
        ref_id = best["id"] if best else None
    if ref_id == req.lap_id:
        # Il giro piu' veloce della pista e' proprio quello analizzato: confrontarlo
        # con se stesso darebbe delta zero ovunque. Si prende il migliore fra gli altri.
        others = [
            r
            for r in hub.db.list_laps(track=lap.get("track"))
            if r["id"] != req.lap_id and r.get("lap_time_ms")
        ]
        ref_id = min(others, key=lambda r: r["lap_time_ms"])["id"] if others else None
    if ref_id is None:
        return {"error": "no_reference"}
    reference = hub.db.get_samples(ref_id)
    track = lap.get("track") or "monza"
    import json

    meta_raw = lap.get("meta_json") or "{}"
    try:
        lap_meta = json.loads(meta_raw) if isinstance(meta_raw, str) else (meta_raw or {})
    except Exception:
        lap_meta = {}
    electronics = lap_meta.get("electronics") or hub._last_electronics
    physics = lap_meta.get("physics_setup") or hub._last_physics_setup
    analysis = build_analysis_payload(
        current,
        reference,
        _track_corners(track),
        meta={
            "track": track,
            "car": lap.get("car"),
            "lap_id": req.lap_id,
            "reference_lap_id": ref_id,
            "current_lap_time_ms": lap.get("lap_time_ms"),
            "reference_lap_time_ms": (hub.db.get_lap(ref_id) or {}).get("lap_time_ms"),
            "electronics": electronics,
        },
        electronics=electronics,
        physics=physics,
    )
    history = [
        {
            "lap_number": r.get("lap_number"),
            "lap_time_ms": r.get("lap_time_ms"),
            "valid": bool(r.get("valid")),
        }
        for r in hub.db.list_laps(track=track, limit=6)
        if r.get("id") != req.lap_id and r.get("lap_time_ms")
    ]
    report = generate_coach_report(
        analysis, force_heuristic=req.force_heuristic, history=history
    )
    path = [
        {"x": s["x"], "z": s["z"], "npos": s.get("npos")}
        for s in current
        if s.get("x") is not None and s.get("z") is not None
    ]
    return {
        "analysis": analysis,
        "coach": report,
        "electronics": electronics,
        "path": path,
        "corners": _track_corners(track),
        "reference": reference,
        "current": current,
        "meta": analysis["meta"],
    }


@app.get("/api/setup/live")
def setup_live() -> dict[str, Any]:
    """Live AC EVO setup instructions from current electronics + last analysis metrics."""
    electronics = hub.latest.get("electronics") or hub._last_electronics or _demo_electronics()
    physics = hub.latest.get("physics_setup") or hub._last_physics_setup or _demo_physics()
    tips = build_acevo_setup_instructions(
        electronics=electronics,
        physics=physics,
        corner_rank=[],
        metrics={},
    )
    return {"electronics": electronics, "setup": tips}


@app.websocket("/ws/live")
async def ws_live(ws: WebSocket) -> None:
    """Stream dei frame live.

    Il tracciato (~28 KB) viene mandato solo quando cambia: dopo il primo giro
    resta identico, e rispedirlo a ogni frame saturava il WiFi verso un secondo
    schermo. Il client tiene l'ultimo ricevuto.
    """
    await ws.accept()
    sent_path_version: int | None = None
    try:
        while True:
            frame = hub.latest
            snapshot = frame.get("map")
            if isinstance(snapshot, dict):
                version = snapshot.get("path_version")
                if version is not None and version == sent_path_version:
                    frame = {
                        **frame,
                        "map": {k: v for k, v in snapshot.items() if k != "path"},
                    }
                else:
                    sent_path_version = version
            await ws.send_json(frame)
            await asyncio.sleep(1.0 / max(HZ, 1.0))
    except WebSocketDisconnect:
        return


# Static frontend
if WEB_DIST.exists():
    assets = WEB_DIST / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(WEB_DIST / "index.html")

    @app.get("/{path:path}")
    def spa_fallback(path: str) -> FileResponse:
        candidate = WEB_DIST / path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(WEB_DIST / "index.html")
