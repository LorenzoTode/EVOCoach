import { useEffect, useState } from "react";
import { formatMs, type DriverComparison } from "./types";

/**
 * I due profili affiancati.
 *
 * Non serve a dire chi va piu' forte — il tempo sul giro lo dice gia'. Serve a
 * rispondere alla domanda per cui i due profili esistono: davanti a due stili
 * diversi il coach dice cose diverse? Se le abitudini divergono e i consigli
 * no, il modello non sta leggendo i dati.
 */
export function DriverCompare({ track }: { track?: string | null }) {
  const [data, setData] = useState<DriverComparison | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let vivo = true;
    void (async () => {
      try {
        const q = track ? `?track=${encodeURIComponent(track)}` : "";
        const res = await fetch(`/api/drivers/compare${q}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const json = (await res.json()) as DriverComparison;
        if (vivo) {
          setData(json);
          setError(null);
        }
      } catch (e) {
        if (vivo) setError(e instanceof Error ? e.message : "Errore di rete");
      }
    })();
    return () => {
      vivo = false;
    };
  }, [track]);

  if (error) return <p className="profile-empty">Confronto non disponibile: {error}</p>;
  if (!data) return <p className="profile-empty">Carico i due profili…</p>;

  const c = data.confronto;
  if (!c.pronti) {
    const manca = (c.giri.a < 2 ? [c.piloti.a] : []).concat(c.giri.b < 2 ? [c.piloti.b] : []);
    return (
      <p className="profile-empty">
        Per confrontare servono almeno due giri validi a testa sulla stessa pista.
        {manca.length ? ` Mancano ancora giri di ${manca.join(" e ")}.` : ""}{" "}
        {c.giri.a} contro {c.giri.b} finora.
      </p>
    );
  }

  return (
    <>
      <div className="compare-head">
        <div>
          <span>{c.piloti.a}</span>
          <strong>{formatMs(c.miglior_giro_ms.a)}</strong>
          <em>
            {c.giri.a} giri · costanza +{(c.consistenza_s.a ?? 0).toFixed(2)}s
          </em>
        </div>
        <div>
          <span>{c.piloti.b}</span>
          <strong>{formatMs(c.miglior_giro_ms.b)}</strong>
          <em>
            {c.giri.b} giri · costanza +{(c.consistenza_s.b ?? 0).toFixed(2)}s
          </em>
        </div>
      </div>

      <p className="compare-note">
        Ordinate per quanto i due divergono: in alto ci sono le differenze di stile
        vere, non il rumore su una metrica già simile.
      </p>

      <ul className="compare-list">
        {c.abitudini.map((r) => {
          const a = r.a ?? 0;
          const b = r.b ?? 0;
          const max = Math.max(Math.abs(a), Math.abs(b), 1e-6);
          return (
            <li key={r.metrica}>
              <div className="compare-row-head">
                <span>{r.etichetta}</span>
                <em>
                  {a}
                  {r.unita} vs {b}
                  {r.unita}
                </em>
              </div>
              <div className="compare-bars">
                <div className="bar a">
                  <i style={{ width: `${(Math.abs(a) / max) * 100}%` }} />
                </div>
                <div className="bar b">
                  <i style={{ width: `${(Math.abs(b) / max) * 100}%` }} />
                </div>
              </div>
            </li>
          );
        })}
      </ul>

      <div className="compare-traits">
        <div>
          <span>Solo {c.piloti.a}</span>
          <p>{c.solo_a.length ? c.solo_a.join(" · ") : "—"}</p>
        </div>
        <div>
          <span>Solo {c.piloti.b}</span>
          <p>{c.solo_b.length ? c.solo_b.join(" · ") : "—"}</p>
        </div>
        <div>
          <span>Tutti e due</span>
          <p>{c.in_comune.length ? c.in_comune.join(" · ") : "—"}</p>
        </div>
      </div>
    </>
  );
}
