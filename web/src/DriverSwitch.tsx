import { useCallback, useEffect, useState } from "react";
import type { Driver } from "./types";

/**
 * Chi ha il volante in mano.
 *
 * Due persone sullo stesso computer: senza dirlo, i giri di uno finiscono nel
 * profilo dell'altro e il coach parla a un pilota che non esiste. Il cambio e'
 * un click perche' succede fra un turno e l'altro, non fra una sessione e
 * l'altra; il nome si cambia con un doppio click, che e' una cosa che si fa
 * una volta sola.
 */
export function DriverSwitch({ activeId, onSwitch }: { activeId?: string; onSwitch: () => void }) {
  const [drivers, setDrivers] = useState<Driver[]>([]);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/drivers");
      if (res.ok) setDrivers(((await res.json()) as { piloti: Driver[] }).piloti);
    } catch {
      /* senza elenco il selettore non si mostra: nessun danno */
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const switchTo = async (id: string) => {
    if (id === activeId || busy) return;
    setBusy(true);
    try {
      const res = await fetch("/api/drivers/active", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id }),
      });
      if (res.ok) {
        setDrivers(((await res.json()) as { piloti: Driver[] }).piloti ?? drivers);
        onSwitch();
      }
    } catch {
      /* riprovabile: il pilota attivo resta quello di prima */
    } finally {
      setBusy(false);
    }
  };

  const rename = async (d: Driver) => {
    const nome = window.prompt("Nome del pilota", d.nome)?.trim();
    if (!nome || nome === d.nome) return;
    try {
      const res = await fetch("/api/drivers/rename", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: d.id, nome }),
      });
      if (res.ok) setDrivers(((await res.json()) as { piloti: Driver[] }).piloti);
    } catch {
      /* il nome resta quello di prima */
    }
  };

  if (drivers.length < 2) return null;

  return (
    <div className="driver-switch" role="group" aria-label="Pilota al volante">
      {drivers.map((d) => (
        <button
          key={d.id}
          type="button"
          className={d.id === activeId ? "active" : ""}
          aria-pressed={d.id === activeId}
          disabled={busy}
          onClick={() => void switchTo(d.id)}
          onDoubleClick={() => void rename(d)}
          title={
            d.id === activeId
              ? "Sta guidando. Doppio click per rinominare."
              : `Passa il volante a ${d.nome}: da qui in poi i giri sono suoi`
          }
        >
          {d.nome}
        </button>
      ))}
    </div>
  );
}
