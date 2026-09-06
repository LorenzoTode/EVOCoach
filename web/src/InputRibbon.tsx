import type { DeltaSegment } from "./types";

type Props = {
  segments: DeltaSegment[];
  npos: number;
};

export function InputRibbon({ segments, npos }: Props) {
  if (!segments.length) return null;
  const w = 600;
  const h = 84;
  const step = w / segments.length;

  const speedMax = Math.max(...segments.map((s) => s.speed || 0), 1);

  return (
    <div className="ribbon">
      <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
        {segments.map((s, i) => {
          const gas = s.gas ?? 0;
          const brake = s.brake ?? 0;
          const spd = (s.speed ?? 0) / speedMax;
          const x = i * step;
          return (
            <g key={i}>
              <rect x={x} y={h - spd * 36} width={Math.max(step - 0.5, 0.5)} height={spd * 36} fill="rgba(140,170,200,0.25)" />
              <rect x={x} y={8} width={Math.max(step - 0.5, 0.5)} height={gas * 20} fill="rgba(46,204,113,0.7)" />
              <rect x={x} y={32} width={Math.max(step - 0.5, 0.5)} height={brake * 20} fill="rgba(231,76,60,0.75)" />
            </g>
          );
        })}
        <line
          x1={npos * w}
          x2={npos * w}
          y1={0}
          y2={h}
          stroke="#f5d76e"
          strokeWidth={2}
        />
      </svg>
      <div className="ribbon-legend">
        <span>Gas</span>
        <span>Freno</span>
        <span>Velocità</span>
      </div>
    </div>
  );
}
