"""SQLite persistence for sessions, laps, and telemetry samples."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

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
            """
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def create_session(self, track: str | None = None, car: str | None = None) -> int:
        cur = self._conn.execute(
            "INSERT INTO sessions (started_at, track, car) VALUES (?, ?, ?)",
            (time.time(), track, car),
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
    ) -> int:
        cur = self._conn.execute(
            """
            INSERT INTO laps (session_id, lap_number, lap_time_ms, valid, track, car, created_at, meta_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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

    def list_laps(self, track: str | None = None, limit: int = 40) -> list[dict[str, Any]]:
        if track:
            rows = self._conn.execute(
                """
                SELECT id, session_id, lap_number, lap_time_ms, valid, track, car, created_at
                FROM laps WHERE track = ? ORDER BY created_at DESC LIMIT ?
                """,
                (track, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT id, session_id, lap_number, lap_time_ms, valid, track, car, created_at
                FROM laps ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
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

    def best_lap(self, track: str | None = None) -> dict[str, Any] | None:
        if track:
            row = self._conn.execute(
                """
                SELECT * FROM laps
                WHERE valid = 1 AND track = ? AND lap_time_ms IS NOT NULL AND lap_time_ms > 0
                ORDER BY lap_time_ms ASC LIMIT 1
                """,
                (track,),
            ).fetchone()
        else:
            row = self._conn.execute(
                """
                SELECT * FROM laps
                WHERE valid = 1 AND lap_time_ms IS NOT NULL AND lap_time_ms > 0
                ORDER BY lap_time_ms ASC LIMIT 1
                """
            ).fetchone()
        return dict(row) if row else None
