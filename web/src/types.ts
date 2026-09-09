export type Sample = {
  t_ms: number;
  npos: number;
  speed?: number;
  gas?: number;
  brake?: number;
  steer?: number;
  x?: number | null;
  y?: number | null;
  z?: number | null;
};

export type DeltaSegment = {
  npos: number;
  delta_ms: number;
  instant_ms: number;
  speed?: number | null;
  speed_ref?: number | null;
  gas?: number | null;
  brake?: number | null;
  x?: number | null;
  z?: number | null;
};

export type Tip = {
  severity?: string;
  title: string;
  detail: string;
  corner?: string;
  corners?: string[];
  npos?: number;
  area?: string;
  menu?: string;
  parameter?: string;
  current?: string | number;
  target?: string | number;
  action?: string;
  /** Da cosa nasce la modifica: l'abitudine o il dato che l'ha motivata. */
  because?: string;
  from_profile?: boolean;
};

export type SessionState = {
  /** waiting_game: il gioco non risponde · waiting_lap: collegati, nessun giro
   *  valido · ready: c'e' almeno un giro valido · demo: dati sintetici */
  state: "waiting_game" | "waiting_lap" | "ready" | "demo";
  track?: string | null;
  car?: string | null;
  lap?: number | null;
  valid_laps: number;
  invalid_laps: number;
  current_lap_valid: boolean;
  best_ms?: number | null;
  /** Il server dice quando c'e' un report nuovo da ritirare. */
  analysis?: {
    version: number;
    running: boolean;
    /** Un'analisi e' in coda e aspetta un momento sicuro per girare. */
    pending?: boolean;
    /** lap = a ogni giro · pit = solo da fermi · manual = solo col pulsante */
    policy?: "lap" | "pit" | "manual";
  };
  last_lap?: {
    lap_id: number;
    lap_time_ms: number | null;
    valid: boolean;
    reasons: string[];
    samples: number;
    npos_span: number;
  } | null;
};

export type LapRow = {
  id: number;
  lap_number?: number | null;
  lap_time_ms?: number | null;
  valid?: number | boolean;
  track?: string | null;
  car?: string | null;
  created_at?: number;
};

export type DriverTrait = {
  severity: string;
  title: string;
  detail: string;
  metric: string;
  value: number;
  /** Negativo = l'abitudine sta calando. */
  trend?: number | null;
  corners?: Array<{ name: string; value: number; laps: number }>;
  /** Tempo perso nelle curve dove il tratto si manifesta. Correlazione. */
  tempo_perso_in_quelle_curve_ms?: number;
  drill?: string;
  check?: string;
};

export type DriverProfile = {
  ready: boolean;
  laps: number;
  best_ms?: number;
  /** Distacco medio dal proprio miglior giro: quanto sei costante. */
  consistenza_s?: number;
  /** Negativa = stai migliorando. */
  tendenza_s?: number | null;
  abitudini?: Record<string, number>;
  tratti?: DriverTrait[];
  track?: string | null;
};

export type CoachReport = {
  summary: string;
  setup: Tip[];
  trajectory: Tip[];
  driving: Tip[];
  driver_note?: string;
  source?: string;
  warning?: string;
};

export type MapSnapshot = {
  track?: string | null;
  /** Assente quando il tracciato non e' cambiato: il client tiene il precedente. */
  path?: Array<{ x: number; z: number; npos?: number }>;
  path_version?: number;
  delta_segments: DeltaSegment[];
  delta_ready: boolean;
  laps_completed: number;
  coverage: number;
  map_ready: boolean;
};

export type LiveFrame = {
  mode?: string;
  connected?: boolean;
  waiting?: boolean;
  track?: string;
  car?: string;
  lap?: number;
  t_ms?: number;
  best_ms?: number | null;
  npos?: number;
  speed?: number;
  gas?: number;
  brake?: number;
  steer?: number;
  rpm?: number;
  gear?: number;
  x?: number | null;
  z?: number | null;
  delta_ms?: number | null;
  slip?: number[];
  electronics?: Record<string, number | null>;
  map?: MapSnapshot;
  corners?: Array<{ id?: number; name: string; start: number; end: number }>;
  session?: SessionState;
  lap_invalid?: boolean;
  tyres_out?: number | null;
  ts?: number;
};

export type AnalyzeResponse = {
  analysis: {
    delta: { final_delta_ms: number; segments: DeltaSegment[] };
    corners: Array<{ name: string; loss_ms: number; mid_npos: number }>;
    metrics: Record<string, number>;
    meta: Record<string, unknown>;
    setup?: Tip[];
  };
  coach: CoachReport;
  path: Array<{ x: number; z: number; npos?: number }>;
  corners: Array<{ id: number; name: string; start: number; end: number }>;
  reference: Sample[];
  current: Sample[];
  meta: Record<string, unknown>;
  electronics?: Record<string, number | null>;
  profile?: DriverProfile;
};

export function formatMs(ms?: number | null): string {
  if (ms == null || Number.isNaN(ms)) return "—";
  const sign = ms < 0 ? "-" : "";
  const abs = Math.abs(ms);
  const m = Math.floor(abs / 60000);
  const s = Math.floor((abs % 60000) / 1000);
  const frac = Math.floor(abs % 1000);
  if (m > 0) return `${sign}${m}:${String(s).padStart(2, "0")}.${String(frac).padStart(3, "0")}`;
  return `${sign}${s}.${String(frac).padStart(3, "0")}`;
}

export function formatDelta(ms?: number | null): string {
  if (ms == null || Number.isNaN(ms)) return "—";
  const sign = ms > 0 ? "+" : ms < 0 ? "−" : "";
  return `${sign}${Math.abs(ms / 1000).toFixed(3)}s`;
}
