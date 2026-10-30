"""Build modello-registro.xlsx, the spreadsheet template for "Compila registro".

    pip install openpyxl && python modello.py

The "Lezioni" sheet has the header the bookmarklet recognises (Data, Dalle,
Alle, Aula, Descrizione, Insegnamento) and pre-formatted rows, so that a
copy from Excel or Google Sheets pastes as text the bookmarklet can parse:
dates as dd/mm/yyyy, times as hh:mm.
"""
from __future__ import annotations

from datetime import date, time
from pathlib import Path

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation

HERE = Path(__file__).resolve().parent
OUT = HERE / 'modello-registro.xlsx'
INSTALL_URL = 'https://acaland.github.io/compila-registro-gomp/'
ROWS = 200

BLUE = PatternFill('solid', fgColor='1E3A8A')
PALE = PatternFill('solid', fgColor='EEF2FF')
WHITE_BOLD = Font(bold=True, color='FFFFFF')
THIN = Border(bottom=Side(style='thin', color='CBD2D9'))
WRAP_TOP = Alignment(wrap_text=True, vertical='top')
TOP = Alignment(vertical='top')

COLUMNS = [
    # header, width, number format, hint
    ('Data', 12, 'DD/MM/YYYY', 'Giorno della lezione, ad esempio 28/02/2026.'),
    ('Dalle', 8, 'HH:MM', 'Ora di inizio, ad esempio 10:00.'),
    ('Alle', 8, 'HH:MM', 'Ora di fine, ad esempio 13:00.'),
    ('Aula', 34, '@', "Testo libero: basta che individui un'aula sola (es. «aula 3 edificio B»)."),
    ('Descrizione', 90, '@', 'Argomenti della lezione. Per andare a capo: Alt+Invio (Windows), Ctrl+Option+Invio (Mac).'),
    ('Insegnamento', 16, '@', 'Facoltativo: codice o parte del nome. Serve solo se hai più insegnamenti.'),
]

EXAMPLE = [
    (date(2026, 2, 28), time(10), time(13), 'aula 3 edificio B',
     'Lezione I - Presentazione del corso e degli strumenti.', ''),
    (date(2026, 5, 28), time(11), time(14), 'aula 3 edificio B',
     'Lezione II - Introduzione a SQL: SELECT, WHERE, operatori logici. Esercizi guidati.', ''),
    (date(2026, 6, 3), time(15, 30), time(18, 30), 'aula magna',
     'Lezione III - JOIN, ORDER BY, GROUP BY e COUNT.', '1001234'),
]


def lessons_sheet(ws) -> None:
    ws.title = 'Lezioni'
    for col, (header, width, fmt, hint) in enumerate(COLUMNS, start=1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font, cell.fill = WHITE_BOLD, BLUE
        cell.comment = Comment(hint, 'Compila registro')
        letter = cell.column_letter
        ws.column_dimensions[letter].width = width
        for row in range(2, ROWS + 2):
            target = ws.cell(row=row, column=col)
            target.number_format = fmt
            target.alignment = WRAP_TOP if header == 'Descrizione' else TOP
            target.border = THIN
    ws.freeze_panes = 'A2'

    last = ROWS + 1
    day = DataValidation(type='date', operator='between', formula1='DATE(2020,1,1)', formula2='DATE(2100,12,31)',
                         allow_blank=True, showErrorMessage=True, errorTitle='Data non valida',
                         error='Scrivi la data come gg/mm/aaaa, ad esempio 28/02/2026.')
    hour = DataValidation(type='time', operator='between', formula1='0', formula2='0.999305555',
                          allow_blank=True, showErrorMessage=True, errorTitle='Orario non valido',
                          error='Scrivi l\'orario come hh:mm, ad esempio 10:00 o 15:30.')
    ws.add_data_validation(day)
    ws.add_data_validation(hour)
    day.add(f'A2:A{last}')
    hour.add(f'B2:C{last}')


def instructions_sheet(ws) -> None:
    ws.title = 'Istruzioni'
    ws.column_dimensions['A'].width = 4
    for letter, (_, width, _, _) in zip('BCDEFG', COLUMNS):
        ws.column_dimensions[letter].width = width
    lines = [
        ('title', 'Modello per «Compila registro»'),
        ('', 'Serve a preparare le lezioni del Registro attività didattiche GOMP in Excel '
             '(o Google Fogli) e incollarle nel segnalibro «Compila registro».'),
        ('', f'Installazione del segnalibro: {INSTALL_URL}'),
        ('', ''),
        ('head', 'Come si compila'),
        ('1', 'Nel foglio «Lezioni» scrivi una riga per lezione. Non cambiare i nomi delle colonne nella riga 1.'),
        ('2', 'Data: gg/mm/aaaa. Dalle e Alle: hh:mm.'),
        ('3', "Aula: testo libero, basta che individui un'aula sola («aula magna», «aula 3 edificio B»). "
              'Se è ambigua, il segnalibro ti mostra le aule possibili.'),
        ('4', 'Descrizione: gli argomenti trattati. Puoi andare a capo nella cella (Alt+Invio su Windows, '
              'Ctrl+Option+Invio su Mac).'),
        ('5', 'Insegnamento: lascialo vuoto se hai un solo insegnamento; altrimenti scrivi il codice o parte del nome.'),
        ('', ''),
        ('head', 'Come si pubblica'),
        ('1', 'Seleziona le celle dalla riga 1 (le intestazioni) all\'ultima lezione, colonne da A a F, e copia (Cmd/Ctrl+C).'),
        ('2', 'Apri il registro GOMP dal portale docenti e clicca il segnalibro «Compila registro».'),
        ('3', 'Incolla nell\'area di testo del pannello (Cmd/Ctrl+V) e premi «Controlla»: vedrai cosa verrà creato o aggiornato, '
              'senza che nulla venga salvato.'),
        ('4', 'Se è tutto corretto premi «Pubblica». Le lezioni già presenti (stessa data e ora di inizio) vengono aggiornate, '
              'le altre create. Nulla viene mai cancellato.'),
        ('', ''),
        ('head', 'Esempio'),
    ]
    row = 1
    for kind, text in lines:
        a, b = ws.cell(row=row, column=1), ws.cell(row=row, column=2, value=text)
        b.alignment = Alignment(wrap_text=True, vertical='top')
        # Prose spans the example table's width; merged cells don't auto-fit.
        ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=7)
        ws.row_dimensions[row].height = 16 * max(1, -(-len(text) // 150))
        if kind == 'title':
            b.font = Font(bold=True, size=16, color='1E3A8A')
            ws.row_dimensions[row].height = 24
        elif kind == 'head':
            b.font = Font(bold=True, size=12, color='1E3A8A')
        elif kind:
            a.value = f'{kind}.'
            a.alignment = Alignment(horizontal='right', vertical='top')
        row += 1

    # The example lives here, not in «Lezioni», so it is never pasted by mistake.
    for col, (header, width, fmt, _) in enumerate(COLUMNS, start=2):
        cell = ws.cell(row=row, column=col, value=header)
        cell.font, cell.fill = WHITE_BOLD, BLUE
    for values in EXAMPLE:
        row += 1
        for col, ((header, width, fmt, _), value) in enumerate(zip(COLUMNS, values), start=2):
            cell = ws.cell(row=row, column=col, value=value)
            cell.number_format, cell.fill = fmt, PALE
            cell.alignment = WRAP_TOP


def main() -> None:
    wb = Workbook()
    lessons_sheet(wb.active)
    instructions_sheet(wb.create_sheet())
    wb.active = 0
    wb.save(OUT)
    print(OUT)


if __name__ == '__main__':
    main()
