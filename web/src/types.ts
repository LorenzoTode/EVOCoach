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
};

export type CoachReport = {
  summary: string;
  setup: Tip[];
  trajectory: Tip[];
  driving: Tip[];
  source?: string;
  warning?: string;
};

export type MapSnapshot = {
  track?: string | null;
  path: Array<{ x: number; z: number; npos?: number }>;
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
