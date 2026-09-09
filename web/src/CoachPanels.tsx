import { useState } from "react";
import { DriverCompare } from "./DriverCompare";
import type { DriverProfile, DriverTrait, Storico, Tip } from "./types";

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
        <li
          key={`${t.title}-${i}`}
          className={`${severityClass(t.severity)}${t.in_coda ? " queued" : ""}`}
        >
          <div className="tip-head">
            <strong>{t.title}</strong>
            {t.corner ? <em>{t.corner}</em> : null}
            {!setupMode && t.area ? <em>{t.area}</em> : null}
            {setupMode && t.azione_ora ? <b className="tag now">Fai questa</b> : null}
            {setupMode && t.in_coda ? <b className="tag queued">In coda</b> : null}
            {t.in_sospeso ? (
              <b className="tag pending">
                {t.volte && t.volte > 1 ? `già detta ${t.volte} volte` : "già detta"}
              </b>
            ) : null}
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
          {t.because ? (
            <p className="tip-because">
              <span>{t.from_profile ? "Dal tuo profilo" : "Perché"}</span>
              {t.because}
            </p>
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
  driverNote?: string;
  setup: Tip[];
  trajectory: Tip[];
  driving: Tip[];
  profile?: DriverProfile;
  source?: string;
  warning?: string;
  metrics?: Record<string, number>;
  storico?: Storico;
  track?: string | null;
};

type TabId = "setup" | "guida" | "profilo" | "confronto";

function TraitCard({ trait }: { trait: DriverTrait }) {
  const trend = trait.trend;
  return (
    <li className={severityClass(trait.severity)}>
      <div className="trait-head">
        <strong>{trait.title}</strong>
        {trend != null && trend !== 0 ? (
          <span className={`trait-trend ${trend < 0 ? "ok" : "bad"}`}>
            {trend < 0 ? "▼" : "▲"} {Math.abs(trend)}
          </span>
        ) : null}
      </div>

      <p>{trait.detail}</p>

      {trait.corners?.length ? (
        <p className="trait-where">
          <span>Soprattutto in</span>
          {trait.corners.map((c) => (
            <em key={c.name}>{c.name}</em>
          ))}
          {trait.tempo_perso_in_quelle_curve_ms ? (
            <b>
              lì perdi {(trait.tempo_perso_in_quelle_curve_ms / 1000).toFixed(2)}s
            </b>
          ) : null}
        </p>
      ) : null}

      {trait.drill ? (
        <div className="trait-drill">
          <span className="drill-label">Da provare nei prossimi due giri</span>
          <p>{trait.drill}</p>
          {trait.check ? <p className="drill-check">Ha funzionato se: {trait.check}</p> : null}
        </div>
      ) : null}
    </li>
  );
}

/**
 * Cos'e' successo all'ultima modifica applicata.
 *
 * E' la riga che trasforma un consiglio in una verifica: senza, ogni giro
 * ricomincia da capo e il pilota non sa se quello che ha cambiato serviva.
 */
function StoricoStrip({ storico }: { storico?: Storico }) {
  if (!storico) return null;
  const esito = storico.esiti_misurati?.[0];
  const sospesi = storico.in_sospeso ?? [];
  if (!esito && !sospesi.length) return null;

  return (
    <div className="storico-strip">
      {esito ? (
        <p className={`storico-esito ${esito.giudizio}`}>
          <span>
            {esito.parametro} {esito.modifica}
          </span>
          {esito.metrica} da {esito.prima ?? "—"} a {esito.dopo ?? "—"} ·{" "}
          <b>{esito.giudizio}</b>
          <em>correlazione, non prova: nello stesso giro è cambiato anche come guidavi</em>
        </p>
      ) : null}
      {sospesi.length ? (
        <p className="storico-sospesi">
          Ancora da applicare: <b>{sospesi[0]}</b>
          {sospesi.length > 1 ? <span> — poi {sospesi.slice(1).join(", ")}</span> : null}
        </p>
      ) : null}
    </div>
  );
}

function ProfilePanel({ profile, note }: { profile?: DriverProfile; note?: string }) {
  if (!profile?.ready) {
    return (
      <p className="profile-empty">
        Il profilo si costruisce sui giri validi: ne servono almeno due sulla stessa
        pista. Finora ne ho {profile?.laps ?? 0}.
      </p>
    );
  }
  const trend = profile.tendenza_s;
  const consistency = profile.consistenza_s ?? 0;
  return (
    <>
      {note ? <p className="profile-note">{note}</p> : null}

      <div className="profile-stats">
        <div>
          <span>Giri letti</span>
          <strong>{profile.laps}</strong>
        </div>
        <div>
          <span>Costanza</span>
          <strong className={consistency > 1 ? "bad" : "ok"}>+{consistency.toFixed(2)}s</strong>
        </div>
        <div>
          <span>Tendenza</span>
          <strong className={trend == null ? "" : trend < 0 ? "ok" : "bad"}>
            {trend == null ? "—" : `${trend > 0 ? "+" : ""}${trend.toFixed(2)}s`}
          </strong>
        </div>
      </div>

      {consistency > 1 ? (
        <p className="profile-warn">
          Prima di toccare qualunque cosa: sei {consistency.toFixed(2)}s in media dal tuo
          giro migliore. Con questa variabilità non si capisce se una modifica funziona.
          Cerca di ripetere lo stesso giro, poi si lavora sul resto.
        </p>
      ) : null}

      {profile.tratti?.length ? (
        <ul className="tips trait-list">
          {profile.tratti.map((t) => (
            <TraitCard key={t.metric} trait={t} />
          ))}
        </ul>
      ) : (
        <p className="profile-empty">
          Nessun vizio ricorrente sopra soglia: gli errori che fai sono episodi, non
          abitudini. Lavora sulle curve dove perdi di più.
        </p>
      )}

      <div className="profile-habits">
        {([
          ["Gas+freno insieme", "overlap_pct", "%"],
          ["Rilascio", "coast_pct", "%"],
          ["Freno in curva", "trail_brake_pct", "%"],
          ["Gas anticipato", "early_throttle_pct", "%"],
          ["Picco freno", "brake_peak", ""],
          ["Slip max", "max_slip", ""],
        ] as const).map(([label, key, unit]) => (
          <div key={key}>
            <span>{label}</span>
            <strong>
              {profile.abitudini?.[key] ?? "—"}
              {unit}
            </strong>
          </div>
        ))}
      </div>
    </>
  );
}

export function CoachPanels({
  summary,
  driverNote,
  setup,
  trajectory,
  driving,
  profile,
  source,
  warning,
  metrics,
  storico,
  track,
}: Props) {
  const [tab, setTab] = useState<TabId>("setup");

  const tabs: Array<{ id: TabId; label: string; count?: number }> = [
    { id: "setup", label: "Setup", count: setup.length },
    { id: "guida", label: "Guida & linee", count: trajectory.length + driving.length },
    { id: "profilo", label: "Profilo", count: profile?.tratti?.length },
    { id: "confronto", label: "Confronto" },
  ];

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

      <div className="coach-tabs" role="tablist">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            className={tab === t.id ? "active" : ""}
            onClick={() => setTab(t.id)}
          >
            {t.label}
            {t.count ? <em>{t.count}</em> : null}
          </button>
        ))}
      </div>

      <div className="coach-tabpanel" role="tabpanel">
        {tab === "setup" ? (
          <section className="panel">
            <div className="panel-title">
              <h3>Setup AC EVO</h3>
              <span>una modifica alla volta</span>
            </div>
            <StoricoStrip storico={storico} />
            <TipList tips={setup} setupMode />
          </section>
        ) : null}

        {tab === "guida" ? (
          <>
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
          </>
        ) : null}

        {tab === "profilo" ? (
          <section className="panel">
            <div className="panel-title">
              <h3>Come guida {profile?.driver_nome ?? "il pilota"}</h3>
              <span>mediana degli ultimi giri validi</span>
            </div>
            <ProfilePanel profile={profile} note={driverNote} />
          </section>
        ) : null}

        {tab === "confronto" ? (
          <section className="panel">
            <div className="panel-title">
              <h3>I due piloti</h3>
              <span>stesso gioco, stili diversi</span>
            </div>
            <DriverCompare track={track} />
          </section>
        ) : null}
      </div>
    </aside>
  );
}
