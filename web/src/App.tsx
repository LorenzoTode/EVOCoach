import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CoachPanels } from "./CoachPanels";
import { InputRibbon } from "./InputRibbon";
import { TrackMap } from "./TrackMap";
import { Waiting } from "./Waiting";
import { Welcome } from "./Welcome";
import {
  formatDelta,
  formatMs,
  type AnalyzeResponse,
  type DeltaSegment,
  type LapRow,
  type LiveFrame,
} from "./types";

function wsUrl() {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}/ws/live`;
}

const EXIT_MS = 420;

/** Sul computer che fa girare il gioco non serve una pagina d'ingresso:
 *  sei gia' li'. Da un altro schermo il benvenuto ha senso. */
function isLocalScreen() {
  const h = window.location.hostname;
  return h === "127.0.0.1" || h === "localhost" || h === "::1" || h === "[::1]";
}

/**
 * Monta i figli con una dissolvenza in entrata e li smonta solo dopo quella
 * in uscita, cosi' le schermate si incrociano invece di sparire di colpo.
 */
function Fade({
  show,
  className = "",
  children,
}: {
  show: boolean;
  className?: string;
  children: React.ReactNode;
}) {
  const [mounted, setMounted] = useState(show);

  useEffect(() => {
    if (show) {
      setMounted(true);
      return;
    }
    const timer = window.setTimeout(() => setMounted(false), EXIT_MS);
    return () => window.clearTimeout(timer);
  }, [show]);

  if (!mounted) return null;
  return <div className={`fade ${show ? "fade-in" : "fade-out"} ${className}`}>{children}</div>;
}

export default function App() {
  const [entered, setEntered] = useState(isLocalScreen);
  const [data, setData] = useState<AnalyzeResponse | null>(null);
  const [live, setLive] = useState<LiveFrame | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [laps, setLaps] = useState<LapRow[]>([]);
  const [lapId, setLapId] = useState<number | null>(null);

  const session = live?.session;
  const sessionState = session?.state ?? "waiting_game";
  const isDemo = sessionState === "demo";
  const validLaps = session?.valid_laps ?? 0;
  // Il cruscotto compare quando c'e' qualcosa da mostrare: un giro valido
  // rilevato, oppure la modalita' dimostrativa.
  const inside = entered && (sessionState === "ready" || isDemo);

  const loadLaps = useCallback(async () => {
    try {
      const res = await fetch("/api/laps");
      if (res.ok) setLaps((await res.json()) as LapRow[]);
    } catch {
      /* la lista giri e' un extra */
    }
  }, []);

  /** id null = giro dimostrativo; un id = un giro vero. */
  const analyze = useCallback(async (id: number | null) => {
    setLoading(true);
    setError(null);
    try {
      const res =
        id == null
          ? await fetch("/api/analyze/demo", { method: "POST" })
          : await fetch("/api/coach", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ use_demo: false, lap_id: id }),
            });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = (await res.json()) as AnalyzeResponse & { error?: string };
      if (json.error) throw new Error(json.error);
      setData(json);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Errore di rete");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let timer: number | undefined;
    let stopped = false;

    const connect = () => {
      ws = new WebSocket(wsUrl());
      ws.onmessage = (ev) => {
        try {
          const next = JSON.parse(ev.data) as LiveFrame;
          setLive((prev) => {
            // Il server omette map.path quando il tracciato non e' cambiato.
            if (next.map && !next.map.path && prev?.map?.path) {
              next.map = { ...next.map, path: prev.map.path };
            }
            return next;
          });
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

  useEffect(() => {
    if (entered) void loadLaps();
  }, [entered, loadLaps, validLaps]);

  // Analisi automatica: parte da sola al primo confronto possibile e a ogni
  // nuovo giro valido, senza che il pilota debba toccare niente.
  const analyzed = useRef<number | null>(null);
  useEffect(() => {
    if (!entered) return;
    if (isDemo) {
      if (analyzed.current !== -1) {
        analyzed.current = -1;
        void analyze(null);
      }
      return;
    }
    const newest = laps[0]?.id;
    // Serve un secondo giro valido: il primo non ha con cosa confrontarsi.
    if (newest && validLaps >= 2 && analyzed.current !== newest) {
      analyzed.current = newest;
      setLapId(newest);
      void analyze(newest);
    }
  }, [entered, isDemo, laps, validLaps, analyze]);

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

  const rawDelta = deltaReady
    ? (live?.delta_ms ??
      liveSegments[Math.floor(npos * Math.max(liveSegments.length, 1))]?.delta_ms ??
      data?.analysis.delta.final_delta_ms)
    : null;
  // Fermi ai box il cronometro del gioco continua a correre e il delta diventa
  // di minuti: non e' un confronto fra giri, e mostrarlo confonde e basta.
  const deltaMs = rawDelta != null && Math.abs(rawDelta) > 60_000 ? null : rawDelta;

  const corners = live?.corners?.length ? live.corners : data?.corners || [];

  const statusLabel = useMemo(() => {
    if (isDemo) return "Demo Monza";
    if (live?.connected) return "Live AC EVO";
    return "Gioco chiuso";
  }, [isDemo, live?.connected]);

  const mapNote = useMemo(() => {
    if (!map) return undefined;
    const cov = Math.round((map.coverage || 0) * 100);
    const track = map.track || live?.track || "?";
    return map.delta_ready
      ? `${track} · delta AC EVO attivo · copertura ${cov}%`
      : `${track} · apprendimento ${cov}%`;
  }, [map, live?.track]);

  return (
    <div className="app-shell">
      <Fade show={!entered}>
        <Welcome onEnter={() => setEntered(true)} />
      </Fade>

      <Fade show={entered && !inside}>
        <Waiting session={session} />
      </Fade>

      <Fade show={inside} className="fade-app">
        <div className="app">
          <header className="topbar">
            <div className="brand-block">
              <p className="brand">ACEVO COACH</p>
              <p className="sub">
                {live?.track || String(data?.meta?.track ?? "—")} ·{" "}
                {live?.car || String(data?.meta?.car ?? "—")}
              </p>
            </div>

            <div className="hud">
              <div>
                <span>Stato</span>
                <strong className={live?.connected && !isDemo ? "ok" : ""}>{statusLabel}</strong>
              </div>
              <div>
                <span>Giro</span>
                <strong className={live?.session?.current_lap_valid === false ? "bad" : ""}>
                  {live?.session?.current_lap_valid === false ? "invalido" : (live?.lap ?? "—")}
                </strong>
              </div>
              <div>
                <span>Tempo</span>
                <strong>{formatMs(live?.t_ms)}</strong>
              </div>
              <div>
                <span>Delta EVO</span>
                <strong className={(deltaMs ?? 0) > 0 ? "bad" : (deltaMs ?? 0) < 0 ? "ok" : ""}>
                  {!deltaReady ? "1° giro" : deltaMs == null ? "—" : formatDelta(deltaMs)}
                </strong>
              </div>
              <div>
                <span>Speed</span>
                <strong>{live?.speed != null ? `${live.speed.toFixed(0)}` : "—"}</strong>
              </div>
            </div>

            <div className="lap-picker">
              {!isDemo && laps.length > 0 ? (
                <select
                  value={lapId ?? ""}
                  onChange={(e) => {
                    const id = Number(e.target.value);
                    setLapId(id);
                    analyzed.current = id;
                    void analyze(id);
                  }}
                  aria-label="Giro da analizzare"
                >
                  {laps.map((l) => (
                    <option key={l.id} value={l.id}>
                      Giro {l.lap_number ?? l.id} · {formatMs(l.lap_time_ms)}
                    </option>
                  ))}
                </select>
              ) : null}
              <button
                type="button"
                className="btn"
                onClick={() => void analyze(isDemo ? null : lapId)}
                disabled={loading}
              >
                {loading ? "Analisi…" : "Rianalizza"}
              </button>
            </div>
          </header>

          {error ? <div className="banner error">{error}</div> : null}

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
                  La mappa si disegna da sola mentre guidi…
                </div>
              )}
            </section>

            {data ? (
              <CoachPanels
                summary={data.coach.summary}
                driverNote={data.coach.driver_note}
                profile={data.profile}
                setup={data.coach.setup}
                trajectory={data.coach.trajectory}
                driving={data.coach.driving}
                source={data.coach.source}
                warning={data.coach.warning}
                metrics={data.analysis.metrics}
              />
            ) : (
              <aside className="coach skeleton">
                {loading
                  ? "Il race engineer sta guardando il tuo giro…"
                  : validLaps === 0
                    ? "Sto imparando il tracciato. Completa un giro valido."
                    : "Serve un secondo giro valido per avere un termine di paragone."}
              </aside>
            )}
          </main>
        </div>
      </Fade>
    </div>
  );
}
