# Compila registro

Un segnalibro per compilare il **Registro attività didattiche** di GOMP / smart_edu
(Università di Catania) scrivendo le lezioni in un'area di testo, oppure
incollandole da Excel, invece di aprire e compilare uno slot alla volta.

**Installazione:** https://acaland.github.io/compila-registro-gomp/

> Progetto indipendente, non affiliato a Be Smart né all'Università. Usa le stesse
> funzioni della pagina del registro, con la sessione del docente: non chiede e non
> salva credenziali, e non cancella mai nulla.

## Installazione

1. Mostra la barra dei preferiti (Chrome/Edge: `Cmd/Ctrl+Shift+B`; Safari: Vista → Mostra barra Preferiti).
2. Apri la [pagina di installazione](https://acaland.github.io/compila-registro-gomp/) e trascina il pulsante **Compila registro** nella barra.

Il segnalibro scarica lo script aggiornato a ogni clic, quindi non va mai reinstallato.
La pagina offre anche una versione "autonoma", con tutto il codice dentro il segnalibro,
che funziona senza connessione a questo sito ma va reinstallata per aggiornarla.

## Uso

1. Entra nel registro come al solito, dal portale docenti.
2. Clicca **Compila registro**: a destra si apre un pannello.
3. Scrivi le lezioni, incollale dal [modello Excel](#modello-excel) o premi **Carica dal registro** per partire da quelle già presenti.
4. **Controlla** mostra cosa verrà creato (+), aggiornato (~) o lasciato com'è (=), e segnala i problemi (!). Non salva nulla.
5. **Pubblica** salva le lezioni senza problemi.

```
Insegnamento: 1001234      (codice o parte del nome; facoltativo se ne hai uno solo)
Aula: aula 3 edificio B    (testo libero: basta che individui un'aula sola)

Sab 28/02/2026 10:00-13:00 aula magna
Lezione I - Presentazione del corso e degli strumenti.

28/05/26 11:00-14:00
Lezione II - Introduzione a SQL: SELECT, WHERE,
operatori logici. Esercizi guidati.
```

- Per ogni lezione serve una riga con data, orario ed eventualmente l'aula, se diversa da quella in cima. Sotto va la descrizione, anche su più righe.
- Le date si possono scrivere come `28/02/2026`, `28-02-26` o `Sab 28/02/2026`; gli orari come `10:00-13:00` o `15.30-18.30`.
- Una lezione è identificata da **data e ora di inizio**: se nel registro esiste già viene aggiornata, altrimenti viene creata.
- Se incolli da Excel, servono la riga di intestazione e le colonne Data, Dalle, Alle, Aula, Descrizione, più Insegnamento se serve: vedi il [modello](#modello-excel).
- Le lezioni nel registro che non compaiono nel testo restano come sono.
- Le date fuori dal periodo modificabile e i mesi già firmati vengono segnalati.

## Modello Excel

Per chi preferisce preparare le lezioni in un foglio di calcolo c'è
[**modello-registro.xlsx**](https://acaland.github.io/compila-registro-gomp/modello-registro.xlsx),
che si può usare anche in Google Fogli.

- Il foglio **Lezioni** ha già le colonne riconosciute dal segnalibro: **Data** (gg/mm/aaaa), **Dalle** e **Alle** (hh:mm), **Aula**, **Descrizione** e **Insegnamento**. Insegnamento è facoltativo e serve solo se ne hai più di uno.
- Le celle sono già formattate e controllano date e orari.
- Il foglio **Istruzioni** spiega i passaggi e contiene un esempio compilato.

Per pubblicare:
1. compila una riga per lezione; nella descrizione puoi andare a capo;
2. seleziona le celle dalla riga delle intestazioni all'ultima lezione (colonne A–F) e copia;
3. nel registro apri **Compila registro**, incolla nell'area di testo, poi **Controlla** e **Pubblica**.

Le righe vuote copiate per errore vengono ignorate.

## Per sviluppatori

- **`registro.js`**: il segnalibro, servito da GitHub Pages.
- **`build.py`**: rigenera `index.html`, la pagina di installazione (`python build.py`).
- **`modello.py`**: rigenera `modello-registro.xlsx` (`pip install openpyxl && python modello.py`).
- **`gomp/`**: libreria e CLI Python sulle stesse API (lettura del registro in YAML, piano, pubblicazione), pensata anche per un futuro uso via MCP. Vedi [gomp/README.md](gomp/README.md).

Le chiamate sono `POST` JSON su `/Professors/ActivityReport/{Init,GetData,FindActivities,FindSpaces,Save}`,
autenticate dal solo cookie di sessione.
