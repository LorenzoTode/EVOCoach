# ACEVO Coach

Race engineer per **Assetto Corsa EVO**. Legge la telemetria dalla memoria
condivisa del gioco, confronta ogni giro con il tuo riferimento e ti dice dove
stai perdendo tempo e cosa cambiare nel setup — con il percorso esatto nel menu
e il valore attuale letto dal gioco.

I giri invalidati (track limits, penalità, flag del gioco) non vengono
considerati: né come giro da analizzare, né come riferimento.

## Avvio

Doppio clic su **`AvviaCoach.bat`**. Si apre il browser da solo.

L'interfaccia si apre su una schermata di benvenuto; premi *Entra* e il
software si mette in attesa. Appena completi un giro cronometrato valido rileva
circuito, vettura e tempi; dal secondo giro valido arriva l'analisi.

### Secondo schermo

L'app ascolta sulla rete locale e all'avvio **stampa l'indirizzo da usare**:

```
  ACEVO COACH
    su questo PC     http://127.0.0.1:8787
    da un altro schermo  http://192.168.1.42:8787
```

Apri quel secondo indirizzo dal portatile, dal telefono o dal tablet. Serve
una regola del firewall sul PC che fa girare l'app, una volta sola, da
PowerShell come amministratore:

```powershell
New-NetFirewallRule -DisplayName "ACEVO Telemetry Coach" -Direction Inbound -LocalPort 8787 -Protocol TCP -Action Allow
```

Tenere l'interfaccia fuori dal PC che fa girare il gioco evita di contendergli
la GPU e di dover fare alt-tab.

## Installazione

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Il frontend è già compilato in `web/dist` e versionato: Node non serve, a meno
di voler modificare l'interfaccia (`cd web && npm install && npm run build`).

## Il coach AI

Senza configurazione l'app usa l'analisi euristica locale: funziona, è gratis,
applica regole fisse. Per avere un coach che *giudica* serve un modello, e si
sceglie in `.env` — copia `.env.example` e leggi lì: ci sono i due backend
(Anthropic e qualunque provider OpenAI-compatibile, compresi quelli con piano
gratuito) con i costi indicativi per giro.

Per sapere quali modelli la tua chiave può davvero usare:

```powershell
.venv\Scripts\python.exe main.py --list-models
```

## Eseguibile

```powershell
python -m pip install pyinstaller
python build_exe.py
```

Produce `dist/ACEVOCoach.exe`. Va costruito su Windows. Il `.env` resta fuori
dall'eseguibile: la chiave API non finisce dentro un binario.

## Opzioni

| Comando | Effetto |
|---|---|
| `main.py` | attende AC EVO, parte senza dati, ascolta sulla rete locale |
| `main.py --mode demo` | giro sintetico di Monza, per provare senza il gioco |
| `main.py --host 127.0.0.1` | solo su questo PC, non dalla rete |
| `main.py --list-models` | modelli disponibili con la chiave configurata |
| `main.py --no-browser` | non apre il browser |
| `main.py --cli` | vecchio monitor da console |

## Com'è fatto

```
telemetry/   lettura della memoria condivisa, mappa del tracciato, demo
analysis/    allineamento per distanza, delta, perdite per curva, setup AC EVO
coach/       report AI (Anthropic o provider OpenAI-compatibile) + euristica
storage/     SQLite: sessioni, giri, campioni
server/      FastAPI: WebSocket live, API di analisi, frontend statico
web/         React + TypeScript
```
