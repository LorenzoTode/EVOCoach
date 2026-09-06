"""Build the driven track outline and delta colouring from live telemetry."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


class TrackMapBuilder:
    """Learn the current circuit from world XZ + npos, then colour with game delta."""

    def __init__(self, bins: int = 360) -> None:
        self.bins = bins
        self.track: str | None = None
        # per-bin best known world position
        self._xz: list[tuple[float, float] | None] = [None] * bins
        self._counts = [0] * bins
        # completed-lap delta profile (npos → delta_ms from AC EVO)
        self._delta_profile: list[float | None] = [None] * bins
        self._lap_delta: list[tuple[float, float]] = []  # (npos, delta_ms) current lap
        self.laps_completed = 0
        self.delta_ready = False
        self._last_lap: int | None = None
        self._last_npos: float | None = None
        # Cambia solo quando il tracciato acquisisce un punto nuovo. Dopo un giro
        # completo si congela, e il WebSocket smette di rispedire ~28 KB per frame.
        self.path_version = 0

    def reset(self, track: str | None = None) -> None:
        self.track = track
        self._xz = [None] * self.bins
        self._counts = [0] * self.bins
        self._delta_profile = [None] * self.bins
        self._lap_delta = []
        self.laps_completed = 0
        self.delta_ready = False
        self._last_lap = None
        self._last_npos = None
        self.path_version += 1

    def _bin(self, npos: float) -> int:
        n = ((float(npos) % 1.0) + 1.0) % 1.0
        return min(self.bins - 1, int(n * self.bins))

    def ingest(self, frame: dict[str, Any]) -> None:
        track = frame.get("track")
        if track and self.track and track != self.track:
            self.reset(track)
        elif track and not self.track:
            self.track = track

        npos = frame.get("npos")
        x, z = frame.get("x"), frame.get("z")
        if npos is None:
            return

        npos_f = float(npos)
        # detect lap wrap / lap number change
        lap = frame.get("lap")
        wrapped = False
        if self._last_npos is not None and npos_f + 0.5 < self._last_npos:
            wrapped = True
        if lap is not None and self._last_lap is not None and lap != self._last_lap:
            wrapped = True

        if wrapped:
            self._finalize_lap()

        self._last_npos = npos_f
        if lap is not None:
            self._last_lap = lap

        if x is not None and z is not None:
            try:
                xf, zf = float(x), float(z)
            except (TypeError, ValueError):
                xf = zf = None  # type: ignore[assignment]
            if xf is not None:
                i = self._bin(npos_f)
                # running average for stability
                prev = self._xz[i]
                if prev is None:
                    self._xz[i] = (xf, zf)
                    self._counts[i] = 1
                    self.path_version += 1
                else:
                    n = self._counts[i] + 1
                    self._xz[i] = (
                        (prev[0] * (n - 1) + xf) / n,
                        (prev[1] * (n - 1) + zf) / n,
                    )
                    self._counts[i] = n

        delta = frame.get("delta_ms")
        best_ms = frame.get("best_ms")
        has_ref = self.laps_completed >= 1 or (isinstance(best_ms, (int, float)) and best_ms > 0)
        if delta is not None and has_ref:
            # Colour using AC EVO delta once a reference / best lap exists
            try:
                self._lap_delta.append((npos_f, float(delta)))
                if has_ref and self.laps_completed >= 1:
                    self.delta_ready = True
                elif isinstance(best_ms, (int, float)) and best_ms > 0:
                    self.delta_ready = True
            except (TypeError, ValueError):
                pass

    def _finalize_lap(self) -> None:
        self.laps_completed += 1
        if self._lap_delta:
            # bake into profile
            for npos, delta in self._lap_delta:
                i = self._bin(npos)
                self._delta_profile[i] = delta
            self.delta_ready = True
        elif self.laps_completed >= 1:
            # first lap done: map can show path; delta colours start next lap
            self.delta_ready = False
        self._lap_delta = []

    @property
    def coverage(self) -> float:
        filled = sum(1 for p in self._xz if p is not None)
        return filled / self.bins

    def path(self) -> list[dict[str, float]]:
        pts: list[dict[str, float]] = []
        for i, p in enumerate(self._xz):
            if p is None:
                continue
            pts.append(
                {"x": round(p[0], 1), "z": round(p[1], 1), "npos": round(i / self.bins, 4)}
            )
        return pts

    def delta_segments(self) -> list[dict[str, float]]:
        """Segments for map colouring. Empty until delta_ready / mid-lap samples."""
        if not self.delta_ready and not self._lap_delta:
            return []

        # merge baked profile with current lap samples
        profile = list(self._delta_profile)
        for npos, delta in self._lap_delta:
            profile[self._bin(npos)] = delta

        segs: list[dict[str, float]] = []
        last: float | None = None
        for i, val in enumerate(profile):
            if val is None:
                if last is not None:
                    val = last
                else:
                    continue
            last = val
            segs.append(
                {
                    "npos": round(i / self.bins, 4),
                    "delta_ms": round(float(val), 1),
                    "instant_ms": 0.0,
                }
            )
        return segs

    # ---- memoria del tracciato fra una sessione e l'altra -----------------
    #
    # Il gioco non pubblica la geometria dei circuiti: questa mappa e' l'unica
    # fonte, e la si ricava guidando. Salvarla significa che la seconda volta
    # che si torna su una pista il tracciato c'e' gia' completo, invece di
    # doverlo ridisegnare da zero ogni sessione.

    @staticmethod
    def _slug(track: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", track.lower()).strip("_") or "sconosciuto"

    def save(self, directory: Path) -> Path | None:
        if not self.track or self.coverage < 0.5:
            return None
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{self._slug(self.track)}.json"
        payload = {
            "track": self.track,
            "bins": self.bins,
            "coverage": round(self.coverage, 4),
            "xz": [[round(p[0], 1), round(p[1], 1)] if p else None for p in self._xz],
        }
        target.write_text(json.dumps(payload), encoding="utf-8")
        return target

    def load(self, directory: Path, track: str) -> bool:
        """Riprende un tracciato gia' imparato. True se ha trovato qualcosa."""
        source = directory / f"{self._slug(track)}.json"
        if not source.is_file():
            return False
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if data.get("bins") != self.bins or not isinstance(data.get("xz"), list):
            return False

        self.track = data.get("track") or track
        self._xz = [
            (float(p[0]), float(p[1])) if isinstance(p, list) and len(p) == 2 else None
            for p in data["xz"]
        ][: self.bins]
        self._xz += [None] * (self.bins - len(self._xz))
        # Un punto ripreso vale come una sola osservazione: le nuove passate
        # lo correggono senza essere schiacciate da una media di mille campioni.
        self._counts = [1 if p else 0 for p in self._xz]
        self.path_version += 1
        return True

    def snapshot(self) -> dict[str, Any]:
        return {
            "track": self.track,
            "path": self.path(),
            "path_version": self.path_version,
            "delta_segments": self.delta_segments(),
            "delta_ready": self.delta_ready or (self.laps_completed >= 1 and bool(self._lap_delta)),
            "laps_completed": self.laps_completed,
            "coverage": round(self.coverage, 3),
            "map_ready": self.coverage >= 0.2 or self.laps_completed >= 1,
        }
