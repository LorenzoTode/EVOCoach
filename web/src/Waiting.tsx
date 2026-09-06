import { formatMs } from "./types";
import type { SessionState } from "./types";

type Props = {
  session?: SessionState;
};

/**
 * Stato d'attesa: il software e' dentro, ma non ha ancora niente da mostrare.
 * Due momenti distinti — il gioco non c'e', oppure c'e' ma manca un giro valido.
 */
export function Waiting({ session }: Props) {
  const state = session?.state ?? "waiting_game";
  const connected = state !== "waiting_game";
  const valid = session?.valid_laps ?? 0;
  const invalid = session?.invalid_laps ?? 0;

  return (
    <div className="screen waiting">
      <div className="waiting-inner">
        <div className={`pulse ${connected ? "live" : ""}`} aria-hidden="true">
          <span />
          <span />
          <span />
        </div>

        <h2>{connected ? "In pista" : "In attesa di Assetto Corsa EVO"}</h2>

        <p className="waiting-lead">
          {connected
            ? valid === 0
              ? "Completa un giro cronometrato: da li' rilevo circuito, tempi e riferimento."
              : "Serve un secondo giro valido per avere un termine di paragone."
            : "Avvia il gioco ed entra in sessione. Da qui non devi fare altro."}
        </p>

        {connected ? (
          <dl className="waiting-facts">
            <div>
              <dt>Circuito</dt>
              <dd>{session?.track || "—"}</dd>
            </div>
            <div>
              <dt>Vettura</dt>
              <dd>{session?.car || "—"}</dd>
            </div>
            <div>
              <dt>Giro</dt>
              <dd>{session?.lap ?? "—"}</dd>
            </div>
            <div>
              <dt>Miglior tempo</dt>
              <dd>{session?.best_ms ? formatMs(session.best_ms) : "—"}</dd>
            </div>
          </dl>
        ) : null}

        {connected ? (
          <div className="waiting-laps">
            <span className="tally ok">
              <strong>{valid}</strong> {valid === 1 ? "giro valido" : "giri validi"}
            </span>
            {invalid > 0 ? (
              <span className="tally bad">
                <strong>{invalid}</strong> {invalid === 1 ? "scartato" : "scartati"}
              </span>
            ) : null}
            {session?.current_lap_valid === false ? (
              <span className="tally warn">giro in corso invalidato</span>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
