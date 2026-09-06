import { useCallback, useEffect, useMemo, useState } from "react";
import { CoachPanels } from "./CoachPanels";
import { InputRibbon } from "./InputRibbon";
import { TrackMap } from "./TrackMap";
import {
  formatDelta,
  formatMs,
  type AnalyzeResponse,
  type DeltaSegment,
  type LiveFrame,
} from "./types";

function wsUrl() {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const host = window.location.host;
  return `${proto}://${host}/ws/live`;
}

export default function App() {
  const [data, setData] = useState<AnalyzeResponse | null>(null);
  const [live, setLive] = useState<LiveFrame | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadAnalysis = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/analyze/demo", { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = (await res.json()) as AnalyzeResponse;
      setData(json);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Errore di rete");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadAnalysis();
  }, [loadAnalysis]);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let timer: number | undefined;
    let stopped = false;

    const connect = () => {
      ws = new WebSocket(wsUrl());
      ws.onmessage = (ev) => {
        try {
          setLive(JSON.parse(ev.data) as LiveFrame);
        } catch {
          /* ignore */
        }
      };
      ws.onclose = () => {
        if (!stopped) timer = window.setTimeout(connect, 1500);
      };
    };
    connect();
    return () => {
      stopped = true;
      if (timer) window.clearTimeout(timer);
      ws?.close();
    };
  }, []);

  const npos = live?.npos ?? 0;
  const map = live?.map;
  const deltaReady = Boolean(map?.delta_ready);
  const livePath = map?.path && map.path.length >= 8 ? map.path : data?.path || [];
  const liveSegments: DeltaSegment[] =
    deltaReady && map?.delta_segments?.length
      ? map.delta_segments
      : deltaReady
        ? data?.analysis.delta.segments || []
        : [];

  const deltaMs = deltaReady
    ? (live?.delta_ms ??
      liveSegments[Math.floor(npos * Math.max(liveSegments.length, 1))]?.delta_ms ??
      data?.analysis.delta.final_delta_ms)
    : null;

  const corners = live?.corners?.length ? live.corners : data?.corners || [];

  const statusLabel = useMemo(() => {
    if (!live) return "Connessione…";
    if (live.mode === "demo") return "Demo Monza";
    if (live.connected) return "Live AC EVO";
    if (live.waiting) return "In attesa del gioco";
    return "Offline";
  }, [live]);

  const mapNote = useMemo(() => {
    if (!map) return undefined;
    const cov = Math.round((map.coverage || 0) * 100);
    if (!map.delta_ready) {
      return `Pista ${map.track || live?.track || "?"} · apprendimento ${cov}% · giro ${map.laps_completed}`;
    }
    return `Pista ${map.track || live?.track || "?"} · delta AC EVO attivo · copertura ${cov}%`;
  }, [map, live?.track]);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand-block">
          <p className="brand">ACEVO COACH</p>
          <p className="sub">
            {live?.track || String(data?.meta?.track ?? "—")} · {live?.car || String(data?.meta?.car ?? "—")}
          </p>
        </div>

        <div className="hud">
          <div>
            <span>Stato</span>
            <strong className={live?.mode === "live" ? "ok" : ""}>{statusLabel}</strong>
          </div>
          <div>
            <span>Giro</span>
            <strong>{live?.lap ?? "—"}</strong>
          </div>
          <div>
            <span>Tempo</span>
            <strong>{formatMs(live?.t_ms)}</strong>
          </div>
          <div>
            <span>Delta EVO</span>
            <strong className={(deltaMs ?? 0) > 0 ? "bad" : (deltaMs ?? 0) < 0 ? "ok" : ""}>
              {deltaReady ? formatDelta(deltaMs) : "1° giro"}
            </strong>
          </div>
          <div>
            <span>Speed</span>
            <strong>{live?.speed != null ? `${live.speed.toFixed(0)}` : "—"}</strong>
          </div>
        </div>

        <button type="button" className="btn" onClick={() => void loadAnalysis()} disabled={loading}>
          {loading ? "Analisi…" : "Rianalizza"}
        </button>
      </header>

      {error ? <div className="banner error">Backend non raggiungibile ({error}). Avvia `python main.py`.</div> : null}

      <main className="layout">
        <section className="map-col">
          {livePath.length >= 2 ? (
            <>
              <TrackMap
                path={livePath}
                segments={liveSegments}
                currentNpos={npos}
                deltaMs={deltaMs}
                deltaReady={deltaReady}
                corners={corners}
                currentSamples={data?.current}
                referenceSamples={data?.reference}
                statusNote={mapNote}
              />
              {data ? <InputRibbon segments={data.analysis.delta.segments} npos={npos} /> : null}
              {data ? (
                <div className="loss-strip">
                  {data.analysis.corners.slice(0, 5).map((c) => (
                    <div key={c.name} className={c.loss_ms > 80 ? "hot" : ""}>
                      <span>{c.name}</span>
                      <strong>
                        {c.loss_ms > 0 ? "+" : ""}
                        {(c.loss_ms / 1000).toFixed(3)}s
                      </strong>
                    </div>
                  ))}
                </div>
              ) : null}
            </>
          ) : (
            <div className="map-placeholder">
              {live?.connected
                ? "In pista: la mappa si disegna automaticamente mentre guidi…"
                : loading
                  ? "Carico telemetria…"
                  : "Nessun dato mappa"}
            </div>
          )}
        </section>

        {data ? (
          <CoachPanels
            summary={data.coach.summary}
            setup={data.coach.setup}
            trajectory={data.coach.trajectory}
            driving={data.coach.driving}
            source={data.coach.source}
            warning={data.coach.warning}
            metrics={data.analysis.metrics}
          />
        ) : (
          <aside className="coach skeleton">Caricamento consigli…</aside>
        )}
      </main>
    </div>
  );
}
