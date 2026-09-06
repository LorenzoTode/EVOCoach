import type { Tip } from "./types";

function sourceLabel(source: string) {
  if (source === "anthropic") return "AI Anthropic";
  if (source === "heuristic") return "Analisi locale";
  return "AI esterna";
}

function severityClass(s?: string) {
  if (s === "high") return "sev-high";
  if (s === "low") return "sev-low";
  return "sev-med";
}

function TipList({ tips, setupMode = false }: { tips: Tip[]; setupMode?: boolean }) {
  if (!tips.length) {
    return <p className="muted">Nessun consiglio in questa sezione.</p>;
  }
  return (
    <ul className="tip-list">
      {tips.map((t, i) => (
        <li key={`${t.title}-${i}`} className={severityClass(t.severity)}>
          <div className="tip-head">
            <strong>{t.title}</strong>
            {t.corner ? <em>{t.corner}</em> : null}
            {!setupMode && t.area ? <em>{t.area}</em> : null}
          </div>
          {setupMode && (t.menu || t.action) ? (
            <div className="setup-card">
              {t.menu ? <p className="setup-menu">{t.menu}</p> : null}
              {t.action ? <p className="setup-action">{t.action}</p> : null}
              {t.current != null || t.target != null ? (
                <p className="setup-values">
                  {t.current != null ? <span>Ora: {String(t.current)}</span> : null}
                  {t.target != null ? <span>Target: {String(t.target)}</span> : null}
                </p>
              ) : null}
            </div>
          ) : null}
          <p>{t.detail}</p>
          {t.corners && t.corners.length ? (
            <p className="tip-corners">{t.corners.join(" · ")}</p>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

type Props = {
  summary: string;
  setup: Tip[];
  trajectory: Tip[];
  driving: Tip[];
  source?: string;
  warning?: string;
  metrics?: Record<string, number>;
};

export function CoachPanels({ summary, setup, trajectory, driving, source, warning, metrics }: Props) {
  return (
    <aside className="coach">
      <header className="coach-summary">
        <p className="eyebrow">Race engineer</p>
        <h2>{summary || "Analisi in corso…"}</h2>
        <div className="meta-row">
          {source ? <span className="pill">{sourceLabel(source)}</span> : null}
          {warning ? <span className="pill warn">{warning}</span> : null}
        </div>
        {metrics ? (
          <div className="metric-grid">
            <div>
              <span>Overlap</span>
              <strong>{metrics.overlap_pct ?? "—"}%</strong>
            </div>
            <div>
              <span>Coast</span>
              <strong>{metrics.coast_pct ?? "—"}%</strong>
            </div>
            <div>
              <span>Slip max</span>
              <strong>{metrics.max_slip ?? "—"}</strong>
            </div>
            <div>
              <span>Media km/h</span>
              <strong>{metrics.avg_speed ?? "—"}</strong>
            </div>
          </div>
        ) : null}
      </header>

      <section className="panel">
        <div className="panel-title">
          <h3>Setup AC EVO</h3>
          <span>menu → valore attuale → target</span>
        </div>
        <TipList tips={setup} setupMode />
      </section>

      <section className="panel">
        <div className="panel-title">
          <h3>Traiettoria</h3>
          <span>linee & punti di corda</span>
        </div>
        <TipList tips={trajectory} />
      </section>

      <section className="panel">
        <div className="panel-title">
          <h3>Guida</h3>
          <span>input & timing</span>
        </div>
        <TipList tips={driving} />
      </section>
    </aside>
  );
}
