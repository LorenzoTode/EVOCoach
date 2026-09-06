type Props = {
  onEnter: () => void;
};

/** Schermata d'ingresso: nessun dato, solo l'invito a entrare. */
export function Welcome({ onEnter }: Props) {
  return (
    <div className="screen welcome">
      <div className="welcome-inner">
        <p className="welcome-eyebrow">Assetto Corsa EVO</p>
        <h1 className="welcome-title">
          ACEVO<span>COACH</span>
        </h1>
        <p className="welcome-lead">
          Il tuo race engineer. Legge la telemetria mentre guidi, confronta
          ogni giro col tuo riferimento e ti dice dove stai perdendo tempo —
          e cosa cambiare nel setup.
        </p>

        <button type="button" className="welcome-btn" onClick={onEnter} autoFocus>
          Entra
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M5 12h13M12 5l7 7-7 7" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>

        <p className="welcome-note">
          Apri il gioco e scendi in pista: il circuito e i tempi vengono
          rilevati da soli. I giri invalidati non vengono considerati.
        </p>
      </div>
    </div>
  );
}
