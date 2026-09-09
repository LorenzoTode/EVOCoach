"""SQLite persistence for sessions, laps, and telemetry samples."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from storage.drivers import DEFAULT_DRIVER
from storage.paths import app_dir

# Accanto all'eseguibile, non al sorgente: dentro un pacchetto PyInstaller il
# sorgente sta in una cartella temporanea che sparisce alla chiusura, e con lei
# sparirebbero tutti i giri registrati.
DEFAULT_DB = app_dir() / "data" / "telemetry.db"


class Database:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path or DEFAULT_DB)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at REAL NOT NULL,
                track TEXT,
                car TEXT,
                notes TEXT
            );

            CREATE TABLE IF NOT EXISTS advice (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                driver TEXT,
                track TEXT,
                lap_id INTEGER,
                created_at REAL NOT NULL,
                lap_time_ms INTEGER,
                delta_ms REAL,
                source TEXT,
                summary TEXT,
                setup_json TEXT,
                metrics_json TEXT,
                electronics_json TEXT
            );

            CREATE TABLE IF NOT EXISTS laps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                lap_number INTEGER,
                lap_time_ms INTEGER,
                valid INTEGER DEFAULT 1,
                track TEXT,
                car TEXT,
                created_at REAL NOT NULL,
                meta_json TEXT,
                FOREIGN KEY(session_id) REFERENCES sessions(id)
            );

            CREATE TABLE IF NOT EXISTS samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lap_id INTEGER NOT NULL,
                t_ms INTEGER NOT NULL,
                npos REAL NOT NULL,
                speed REAL,
                gas REAL,
                brake REAL,
                steer REAL,
                rpm REAL,
                gear INTEGER,
                x REAL,
                y REAL,
                z REAL,
                slip_fl REAL,
                slip_fr REAL,
                slip_rl REAL,
                slip_rr REAL,
                FOREIGN KEY(lap_id) REFERENCES laps(id)
            );

            CREATE INDEX IF NOT EXISTS idx_samples_lap ON samples(lap_id, npos);
            CREATE INDEX IF NOT EXISTS idx_laps_track ON laps(track, lap_time_ms);
            CREATE INDEX IF NOT EXISTS idx_advice_who ON advice(driver, track, created_at);
            """
        )
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        """Aggiunge la colonna del pilota agli archivi nati prima dei profili.

        I giri gia' registrati sono di chi usava l'app fino a ieri: vanno al
        primo pilota, non a nessuno. Un NULL li renderebbe invisibili a
        qualunque filtro, cioe' li cancellerebbe di fatto.
        """
        for table in ("laps", "sessions"):
            colonne = {r["name"] for r in self._conn.execute(f"PRAGMA table_info({table})")}
            if "driver" not in colonne:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN driver TEXT")
        self._conn.execute(
            "UPDATE laps SET driver = ? WHERE driver IS NULL OR driver = ''", (DEFAULT_DRIVER,)
        )
        self._conn.execute(
            "UPDATE sessions SET driver = ? WHERE driver IS NULL OR driver = ''", (DEFAULT_DRIVER,)
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_laps_driver ON laps(driver, track, lap_time_ms)"
        )

    def close(self) -> None:
        self._conn.close()

    def create_session(
        self,
        track: str | None = None,
        car: str | None = None,
        driver: str = DEFAULT_DRIVER,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO sessions (started_at, track, car, driver) VALUES (?, ?, ?, ?)",
            (time.time(), track, car, driver),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def save_lap(
        self,
        session_id: int,
        *,
        lap_number: int | None,
        lap_time_ms: int | None,
        track: str | None,
        car: str | None,
        samples: list[dict[str, Any]],
        valid: bool = True,
        meta: dict[str, Any] | None = None,
        driver: str = DEFAULT_DRIVER,
    ) -> int:
        cur = self._conn.execute(
            """
            INSERT INTO laps (session_id, lap_number, lap_time_ms, valid, track, car,
                              created_at, meta_json, driver)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                lap_number,
                lap_time_ms,
                1 if valid else 0,
                track,
                car,
                time.time(),
                json.dumps(meta or {}),
                driver,
            ),
        )
        lap_id = int(cur.lastrowid)
        rows = [
            (
                lap_id,
                int(s.get("t_ms") or 0),
                float(s.get("npos") or 0.0),
                s.get("speed"),
                s.get("gas"),
                s.get("brake"),
                s.get("steer"),
                s.get("rpm"),
                s.get("gear"),
                s.get("x"),
                s.get("y"),
                s.get("z"),
                s.get("slip_fl"),
                s.get("slip_fr"),
                s.get("slip_rl"),
                s.get("slip_rr"),
            )
            for s in samples
        ]
        self._conn.executemany(
            """
            INSERT INTO samples (
                lap_id, t_ms, npos, speed, gas, brake, steer, rpm, gear,
                x, y, z, slip_fl, slip_fr, slip_rl, slip_rr
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self._conn.commit()
        return lap_id

    def list_laps(
        self,
        track: str | None = None,
        limit: int = 40,
        driver: str | None = None,
    ) -> list[dict[str, Any]]:
        """Giri archiviati, dal piu' recente.

        driver=None non filtra: serve all'export e al confronto fra piloti.
        Chi costruisce un profilo o cerca un riferimento deve passarlo, o
        finisce per mescolare due persone in una sola media.
        """
        where, args = [], []
        if track:
            where.append("track = ?")
            args.append(track)
        if driver:
            where.append("driver = ?")
            args.append(driver)
        clausola = f"WHERE {' AND '.join(where)}" if where else ""
        args.append(limit)
        rows = self._conn.execute(
            f"""
            SELECT id, session_id, lap_number, lap_time_ms, valid, track, car, created_at, driver
            FROM laps {clausola} ORDER BY created_at DESC LIMIT ?
            """,
            args,
        ).fetchall()
        return [dict(r) for r in rows]

    def get_lap(self, lap_id: int) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM laps WHERE id = ?", (lap_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_samples(self, lap_id: int) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM samples WHERE lap_id = ? ORDER BY npos ASC, t_ms ASC",
            (lap_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def best_lap(self, track: str | None = None, driver: str | None = None) -> dict[str, Any] | None:
        """Il giro di riferimento.

        Con due piloti sulla stessa macchina il riferimento resta il proprio
        miglior giro: confrontarsi col migliore dell'altro darebbe un delta
        che parla di un'altra persona, e consigli tarati su di lei.
        """
        where, args = ["valid = 1", "lap_time_ms IS NOT NULL", "lap_time_ms > 0"], []
        if track:
            where.append("track = ?")
            args.append(track)
        if driver:
            where.append("driver = ?")
            args.append(driver)
        row = self._conn.execute(
            f"SELECT * FROM laps WHERE {' AND '.join(where)} ORDER BY lap_time_ms ASC LIMIT 1",
            args,
        ).fetchone()
        return dict(row) if row else None

    # ---- consigli gia' dati ---------------------------------------------

    def save_advice(
        self,
        *,
        driver: str,
        track: str | None,
        lap_id: int | None,
        lap_time_ms: int | None,
        delta_ms: float | None,
        source: str | None,
        summary: str | None,
        setup: list[dict[str, Any]] | None,
        metrics: dict[str, Any] | None,
        electronics: dict[str, Any] | None,
    ) -> int:
        """Archivia cosa e' stato consigliato, per non ripeterlo alla cieca."""
        cur = self._conn.execute(
            """
            INSERT INTO advice (driver, track, lap_id, created_at, lap_time_ms, delta_ms,
                                source, summary, setup_json, metrics_json, electronics_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                driver,
                track,
                lap_id,
                time.time(),
                lap_time_ms,
                delta_ms,
                source,
                summary,
                json.dumps(setup or [], ensure_ascii=False, default=str),
                json.dumps(metrics or {}, ensure_ascii=False, default=str),
                json.dumps(electronics or {}, ensure_ascii=False, default=str),
            ),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def list_advice(
        self, driver: str, track: str | None = None, limit: int = 6
    ) -> list[dict[str, Any]]:
        """I consigli precedenti dello stesso pilota, dal piu' recente."""
        where, args = ["driver = ?"], [driver]
        if track:
            where.append("track = ?")
            args.append(track)
        args.append(limit)
        rows = self._conn.execute(
            f"SELECT * FROM advice WHERE {' AND '.join(where)} ORDER BY created_at DESC LIMIT ?",
            args,
        ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            for campo, chiave in (("setup_json", "setup"), ("metrics_json", "metrics"),
                                  ("electronics_json", "electronics")):
                try:
                    item[chiave] = json.loads(item.pop(campo) or ("[]" if chiave == "setup" else "{}"))
                except (ValueError, TypeError):
                    item[chiave] = [] if chiave == "setup" else {}
            out.append(item)
        return out
