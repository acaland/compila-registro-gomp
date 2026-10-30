"""Build index.html, the install page for the "Compila registro" bookmarklet.

    python build.py [--script-url https://.../registro.js]

GitHub Pages serves index.html and registro.js from the repository root.
The page offers up to two links to drag onto the bookmarks bar:
  - the loader (only with --script-url): a one-liner that fetches registro.js
    at every click, so updates reach everyone without reinstalling;
  - the standalone version: the whole script inside the bookmark. It needs no
    hosting, but has to be reinstalled to update.
"""
from __future__ import annotations

import argparse
import html
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
SCRIPT_URL = 'https://acaland.github.io/compila-registro-gomp/registro.js'
REPO_URL = 'https://github.com/acaland/compila-registro-gomp'


def loader(script_url: str) -> str:
    return (
        "javascript:(()=>{const s=document.createElement('script');"
        f"s.src='{script_url}?t='+Date.now();"
        "s.onerror=()=>alert('Impossibile caricare Compila registro.');"
        "document.body.appendChild(s)})()"
    )


def standalone(source: str) -> str:
    return 'javascript:' + quote(source, safe="!*'();:@&=+$,/?[]~-_.")


def link(href: str, label: str) -> str:
    return f'<a class="bm" href="{html.escape(href, quote=True)}">{html.escape(label)}</a>'


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--script-url', default=SCRIPT_URL, help='Public HTTPS URL of registro.js; empty for standalone only.')
    args = parser.parse_args()

    source = (HERE / 'registro.js').read_text()
    version = source.split("const VERSION = '")[1].split("'")[0]
    links = []
    if args.script_url:
        links.append(f'<p>{link(loader(args.script_url), "Compila registro")} '
                     '<small>si aggiorna da solo</small></p>')
    links.append(f'<p>{link(standalone(source), "Compila registro (autonomo)")} '
                 f'<small>versione {version}, da reinstallare per aggiornarla</small></p>')

    page = f"""<!doctype html>
<html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Compila registro</title>
<style>
  body {{ font: 16px/1.5 system-ui, sans-serif; max-width: 680px; margin: 40px auto; padding: 0 16px; color: #1f2933; background: #fff; }}
  a.bm {{ display: inline-block; padding: 8px 16px; background: #1e3a8a; color: #fff; border-radius: 6px; text-decoration: none; font-weight: 600; }}
  small {{ color: #616e7c; margin-left: 8px; }}
  li {{ margin: 6px 0; }}
</style></head><body>
<h1>Compila registro</h1>
<p>Compila il <b>Registro attività didattiche</b> GOMP incollando le lezioni come testo
o come celle di Excel, invece di aprire uno slot alla volta.</p>
<p><small style="margin:0">Progetto indipendente, non affiliato a Be Smart né all'Università.
Codice e istruzioni: <a href="{REPO_URL}">{REPO_URL}</a></small></p>
<h2>Installazione</h2>
<ol>
  <li>Mostra la barra dei preferiti (Chrome/Edge: <kbd>Cmd/Ctrl+Shift+B</kbd>; Safari: Vista → Mostra barra Preferiti).</li>
  <li>Trascina questo pulsante nella barra:</li>
</ol>
{''.join(links)}
<h2>Preparare le lezioni in Excel</h2>
<p>Scarica il <a href="modello-registro.xlsx" download>modello Excel</a> (va bene anche Google Fogli):
una riga per lezione con Data, Dalle, Alle, Aula, Descrizione e, se hai più insegnamenti, Insegnamento.
Poi seleziona le celle dalla riga delle intestazioni all'ultima lezione, copia e incolla nel pannello.
Le istruzioni sono anche nel foglio «Istruzioni» del file.</p>
<h2>Uso</h2>
<ol>
  <li>Entra nel registro come al solito, dal portale docenti.</li>
  <li>Clicca il segnalibro <b>Compila registro</b>: si apre un pannello a destra.</li>
  <li>Scrivi o incolla le lezioni, oppure premi <b>Carica dal registro</b> per partire da quelle già presenti.</li>
  <li><b>Controlla</b> mostra cosa verrà creato o aggiornato, senza salvare nulla.</li>
  <li><b>Pubblica</b> salva. Nulla viene mai cancellato.</li>
</ol>
</body></html>
"""
    out = HERE / 'index.html'
    out.write_text(page)
    print(f'{out}  (standalone bookmarklet: {len(standalone(source)) // 1024} KB)')


if __name__ == '__main__':
    main()
