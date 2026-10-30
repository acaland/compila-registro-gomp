# gomp: libreria e CLI Python per il registro GOMP

Compila il registro su https://unict-segreteriecore.gomp.it/Professors/ActivityReport
partendo da un file YAML con una riga per lezione. Non usa il browser: parla
direttamente con l'API JSON che usa la pagina web.

```bash
# dalla radice del repository
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m gomp login                       # apre o rinnova la sessione
.venv/bin/python -m gomp pull --anno 2025            # GOMP -> gomp/registro_2025.yaml
.venv/bin/python -m gomp apply gomp/registro_2025.yaml          # mostra il piano
.venv/bin/python -m gomp apply gomp/registro_2025.yaml --save   # scrive
```

I file `gomp/registro_*.yaml` e la cartella `gomp/auth/` (cookie di sessione)
restano fuori da git.

`apply` crea le lezioni che mancano e aggiorna quelle che esistono già: stessa
data e stessa ora di inizio. **Non elimina mai nulla.** Gli slot presenti solo
su GOMP vengono elencati e lasciati come sono. Le lezioni fuori dal periodo
modificabile (`EnabledTo` dell'anno accademico) o in un mese già firmato
risultano "bloccate".

## Il file YAML

```yaml
anno_accademico: 2025          # 2025 = A.A. 2025/26
insegnamento: '1001234'        # codice attività GOMP
aula: AULA 3 - EDIFICIO B    # come la scrive GOMP
tipo: Didattica frontale       # inizio della descrizione del tipo di attività
lezioni:
- data: 2026-02-28
  dalle: '10:00'
  alle: '13:00'
  descrizione: >
    Lezione I - ...
  # aula / insegnamento / tipo: facoltativi, sovrascrivono i valori sopra
```

## Autenticazione

La catena di login è questa:
1. il CAS di Ateneo (`iam.unict.it`), con codice fiscale e password;
2. il portale docenti `docenti.smartedu.unict.it`;
3. `/NetCoreSignOn?url=/Professors/ActivityReport`;
4. il reindirizzamento a GOMP, `/Login/SinleSignOn/...`, che apre la sessione.

`open_client` prova i passi dal più economico:
1. i cookie salvati in `gomp/auth/cookies.json` (non versionato, permessi 600);
2. il single sign-on dal portale, che non chiede la password finché la sessione CAS è viva;
3. il login CAS con le credenziali salvate, solo con `--auto-login`, attivo per default.

Le credenziali non stanno mai nel repository. Si cercano in quest'ordine:
- le variabili `GOMP_USERNAME` e `GOMP_PASSWORD`;
- nel portachiavi macOS, una password generica con servizio `gomp-unict`. Si crea una volta, e il comando chiede la password senza mostrarla:
  ```bash
  security add-generic-password -s gomp-unict -a <codice fiscale> -w
  ```
- nel portachiavi macOS, una password internet salvata per `iam.unict.it`.

macOS chiede il permesso a ogni lettura dal portachiavi ("Consenti sempre" per non vederlo più).

SPID, CIE e l'accesso @UNICT non sono automatizzabili. Con quei metodi si entra
dal browser, e lo script funziona finché la sessione CAS resta valida.

## Come è fatto

| File | Ruolo |
|---|---|
| `client.py` | `GompClient`: un metodo per endpoint, conversione delle date (il client web invia UTC, il server risponde in ora di Roma) |
| `auth.py` | credenziali, cookie, catena CAS → portale → GOMP |
| `registro.py` | modello YAML (pydantic), `pull`, `plan`, `apply` |
| `cli.py` | comandi `login`, `pull`, `apply` |

Endpoint usati, tutti `POST` JSON sotto `/Professors/ActivityReport/`:
- `Init`
- `GetData {DateFrom, DateTo}`
- `FindActivities`
- `FindSpaces`
- `Save {item}`: senza `UID` crea, con `UID` aggiorna
- `Remove {item}`: non usato dalla CLI

## Evoluzione prevista: Moodle → registro via MCP

L'obiettivo è che un docente possa chiedere all'assistente "leggi le lezioni
da Moodle e compila il registro". Il codice è già diviso per permetterlo:

- **La libreria non stampa e non chiede nulla.** `pull`, `plan` e `apply`
  restituiscono oggetti (`Registro`, `Plan`, `Action`). Un server MCP potrà
  esporli come tool (`gomp_pull`, `gomp_plan`, `gomp_apply`) e mostrare il
  piano al docente prima di scrivere, come fa oggi `apply` senza `--save`.
- **L'autenticazione non dipende dal terminale.** Su un server le credenziali
  arrivano da variabili d'ambiente o da un secret store, e `open_client`
  non cambia.
- **Data, orario e aula vivranno su Moodle.**
  - In moodlecraft ogni sezione-lezione avrà un blocco facoltativo, per esempio
    `lezione: {data, dalle, alle, aula}` in `section.yaml`.
  - L'`apply` di moodlecraft lo scriverà in modo leggibile nel sommario della
    sezione ("Sab 28/02/2026, 10:00–13:00, Aula 3"), con i dati anche in un
    attributo `data-*`, così si potranno rileggere da Moodle senza ambiguità.
  - La descrizione per il registro nascerà dal nome e dal sommario della
    sezione. Il passaggio Moodle → `Registro` sarà una funzione pura, e da lì
    si userà questa stessa `plan`/`apply`.

