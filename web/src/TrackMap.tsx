import { useEffect, useMemo, useRef } from "react";
import type { DeltaSegment, Sample } from "./types";

type Pt = { x: number; z: number; npos?: number };

type Props = {
  path: Pt[];
  segments: DeltaSegment[];
  currentNpos: number;
  deltaMs?: number | null;
  deltaReady?: boolean;
  corners: Array<{ name: string; start: number; end: number }>;
  currentSamples?: Sample[];
  referenceSamples?: Sample[];
  statusNote?: string;
};

function bounds(points: Pt[]) {
  const xs = points.map((p) => p.x);
  const zs = points.map((p) => p.z);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minZ = Math.min(...zs);
  const maxZ = Math.max(...zs);
  const pad = Math.max(maxX - minX, maxZ - minZ) * 0.08 || 40;
  return { minX: minX - pad, maxX: maxX + pad, minZ: minZ - pad, maxZ: maxZ + pad };
}

function project(p: Pt, b: ReturnType<typeof bounds>, w: number, h: number) {
  const bw = b.maxX - b.minX || 1;
  const bh = b.maxZ - b.minZ || 1;
  const scale = Math.min(w / bw, h / bh);
  const ox = (w - bw * scale) / 2;
  const oy = (h - bh * scale) / 2;
  return {
    x: ox + (p.x - b.minX) * scale,
    y: oy + (p.z - b.minZ) * scale,
  };
}

function lerpPath(path: Pt[], npos: number): Pt {
  if (!path.length) return { x: 0, z: 0 };
  const n = ((npos % 1) + 1) % 1;

  // Prefer normalized-position interpolation when points carry npos (live-learned maps)
  if (path.some((p) => p.npos != null)) {
    const ordered = [...path].sort((a, b) => (a.npos ?? 0) - (b.npos ?? 0));
    if (n <= (ordered[0].npos ?? 0)) return ordered[0];
    for (let i = 1; i < ordered.length; i++) {
      const a = ordered[i - 1];
      const c = ordered[i];
      const na = a.npos ?? 0;
      const nc = c.npos ?? 1;
      if (n <= nc) {
        const t = (n - na) / (nc - na || 1);
        return { x: a.x + (c.x - a.x) * t, z: a.z + (c.z - a.z) * t, npos: n };
      }
    }
    return ordered[ordered.length - 1];
  }

  const lengths = [0];
  for (let i = 1; i < path.length; i++) {
    const dx = path[i].x - path[i - 1].x;
    const dz = path[i].z - path[i - 1].z;
    lengths.push(lengths[i - 1] + Math.hypot(dx, dz));
  }
  const total = lengths[lengths.length - 1] || 1;
  const target = n * total;
  for (let i = 1; i < path.length; i++) {
    if (lengths[i] >= target) {
      const seg = lengths[i] - lengths[i - 1] || 1;
      const t = (target - lengths[i - 1]) / seg;
      return {
        x: path[i - 1].x + (path[i].x - path[i - 1].x) * t,
        z: path[i - 1].z + (path[i].z - path[i - 1].z) * t,
      };
    }
  }
  return path[path.length - 1];
}

function deltaColor(delta: number, maxAbs = 1200): string {
  const t = Math.max(-1, Math.min(1, delta / maxAbs));
  if (t <= 0) {
    const a = Math.min(1, Math.abs(t) * 1.2 + 0.25);
    return `rgba(46, 204, 113, ${a})`;
  }
  const a = Math.min(1, t * 1.2 + 0.25);
  return `rgba(231, 76, 60, ${a})`;
}

export function TrackMap({
  path,
  segments,
  currentNpos,
  deltaMs,
  deltaReady = false,
  corners,
  currentSamples,
  referenceSamples,
  statusNote,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const size = useMemo(() => ({ w: 900, h: 720 }), []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || path.length < 2) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    canvas.width = size.w * dpr;
    canvas.height = size.h * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const b = bounds(path);
    const projected = path.map((p) => project(p, b, size.w, size.h));

    const g = ctx.createRadialGradient(size.w * 0.45, size.h * 0.4, 40, size.w * 0.5, size.h * 0.5, size.w * 0.7);
    g.addColorStop(0, "#1c242c");
    g.addColorStop(1, "#0d1116");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, size.w, size.h);

    ctx.strokeStyle = "rgba(255,255,255,0.03)";
    ctx.lineWidth = 1;
    for (let i = 0; i < 12; i++) {
      const x = (size.w / 12) * i;
      const y = (size.h / 12) * i;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, size.h);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(size.w, y);
      ctx.stroke();
    }

    // asphalt ribbon (open path — learned from current track)
    ctx.beginPath();
    projected.forEach((p, i) => (i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y)));
    ctx.strokeStyle = "#2a3340";
    ctx.lineWidth = 22;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.stroke();
    ctx.strokeStyle = "#3d4a5c";
    ctx.lineWidth = 16;
    ctx.stroke();

    // Colour only after first lap / when AC EVO delta is active
    if (deltaReady && segments.length > 1) {
      for (let i = 0; i < segments.length - 1; i++) {
        const a = lerpPath(path, segments[i].npos);
        const c = lerpPath(path, segments[i + 1].npos);
        const pa = project(a, b, size.w, size.h);
        const pc = project(c, b, size.w, size.h);
        ctx.beginPath();
        ctx.moveTo(pa.x, pa.y);
        ctx.lineTo(pc.x, pc.y);
        ctx.strokeStyle = deltaColor(segments[i].delta_ms);
        ctx.lineWidth = 8;
        ctx.lineCap = "round";
        ctx.stroke();
      }
    }

    const refPts = (referenceSamples || [])
      .filter((s) => s.x != null && s.z != null)
      .map((s) => project({ x: s.x!, z: s.z! }, b, size.w, size.h));
    if (refPts.length > 2) {
      // Alone scuro sotto: la linea blu resta leggibile anche sull'asfalto.
      ctx.beginPath();
      refPts.forEach((p, i) => (i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y)));
      ctx.strokeStyle = "rgba(4, 10, 20, 0.55)";
      ctx.lineWidth = 6;
      ctx.lineJoin = "round";
      ctx.lineCap = "round";
      ctx.stroke();

      ctx.beginPath();
      refPts.forEach((p, i) => (i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y)));
      ctx.strokeStyle = "#4a9eff";
      ctx.lineWidth = 3;
      ctx.stroke();
    }

    // Il giro corrente non e' una linea sola: ogni tratto prende il colore del
    // delta in quel punto, cosi' si vede *dove* si guadagna e dove si perde.
    const curSamples = (currentSamples || []).filter((s) => s.x != null && s.z != null);
    if (curSamples.length > 2) {
      const deltaAt = (npos: number) => {
        if (!segments.length) return 0;
        const i = Math.min(segments.length - 1, Math.max(0, Math.round(npos * segments.length)));
        return segments[i]?.delta_ms ?? 0;
      };
      ctx.lineWidth = 3.5;
      ctx.lineCap = "round";
      for (let i = 0; i < curSamples.length - 1; i++) {
        const a = project({ x: curSamples[i].x!, z: curSamples[i].z! }, b, size.w, size.h);
        const c = project({ x: curSamples[i + 1].x!, z: curSamples[i + 1].z! }, b, size.w, size.h);
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(c.x, c.y);
        ctx.strokeStyle = deltaColor(deltaAt(curSamples[i].npos));
        ctx.stroke();
      }
    }

    ctx.font = "600 12px 'IBM Plex Sans', sans-serif";
    corners.forEach((c) => {
      const mid = (c.start + c.end) / 2;
      const pt = project(lerpPath(path, mid), b, size.w, size.h);
      ctx.fillStyle = "rgba(255,255,255,0.55)";
      ctx.beginPath();
      ctx.arc(pt.x, pt.y, 3, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "rgba(230, 236, 245, 0.7)";
      ctx.fillText(c.name, pt.x + 8, pt.y - 8);
    });

    const car = project(lerpPath(path, currentNpos), b, size.w, size.h);
    const liveDelta = deltaReady ? (deltaMs ?? 0) : 0;
    if (deltaReady) {
      ctx.beginPath();
      ctx.arc(car.x, car.y, 16, 0, Math.PI * 2);
      ctx.fillStyle = deltaColor(liveDelta, 800);
      ctx.globalAlpha = 0.35;
      ctx.fill();
      ctx.globalAlpha = 1;
    }
    ctx.beginPath();
    ctx.arc(car.x, car.y, 7, 0, Math.PI * 2);
    ctx.fillStyle = !deltaReady
      ? "#f5f7fa"
      : liveDelta > 20
        ? "#e74c3c"
        : liveDelta < -20
          ? "#2ecc71"
          : "#f5f7fa";
    ctx.fill();
    ctx.strokeStyle = "#0b0e12";
    ctx.lineWidth = 2;
    ctx.stroke();
  }, [path, segments, currentNpos, deltaMs, deltaReady, corners, currentSamples, referenceSamples, size]);

  return (
    <div className="track-wrap">
      <canvas ref={canvasRef} className="track-canvas" style={{ width: "100%", height: "100%" }} />
      <div className="track-legend">
        {statusNote ? <span>{statusNote}</span> : null}
        {referenceSamples?.length ? <span className="ref">Blu = giro di riferimento</span> : null}
        {deltaReady ? (
          <>
            <span className="gain">Verde = guadagni</span>
            <span className="loss">Rosso = perdi</span>
          </>
        ) : (
          <span>Mappa in apprendimento — delta dopo il 1° giro</span>
        )}
      </div>
    </div>
  );
}
