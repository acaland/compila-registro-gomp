from __future__ import annotations

from datetime import date
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from . import registro as reg
from .auth import AuthError, open_client
from .client import GompError, from_wire


console = Console()
HERE = Path(__file__).resolve().parent


def _client(ctx: click.Context):
    try:
        return open_client(auto_login=ctx.obj['auto_login'])
    except (AuthError, GompError) as exc:
        raise click.ClickException(str(exc)) from exc


@click.group()
@click.option('--auto-login/--no-auto-login', default=True,
              help='When the saved session has expired, log in on CAS with the stored credentials.')
@click.pass_context
def cli(ctx: click.Context, auto_login: bool) -> None:
    """Fill the unict GOMP teaching register (Registro attivita' didattiche) from a YAML file."""
    ctx.obj = {'auto_login': auto_login}


@cli.command()
@click.pass_context
def login(ctx: click.Context) -> None:
    """Open (or renew) the GOMP session and save it in gomp/auth/."""
    client = _client(ctx)
    period = client.get_data(date.today(), date.today())['period']
    console.print(f'[green]GOMP session active.[/green] Current academic year: {period["Description"]}.')


@cli.command()
@click.option('--anno', type=int, help='Academic year by its first calendar year (2025 = 2025/26). Default: current.')
@click.option('--out', type=click.Path(dir_okay=False, path_type=Path), help='Default: gomp/registro_<anno>.yaml')
@click.pass_context
def pull(ctx: click.Context, anno: int | None, out: Path | None) -> None:
    """Write what GOMP holds for an academic year into a YAML file."""
    client = _client(ctx)
    try:
        registro, skipped = reg.pull(client, anno)
    except GompError as exc:
        raise click.ClickException(str(exc)) from exc
    out = out or HERE / f'registro_{registro.anno_accademico}.yaml'
    year = f'{registro.anno_accademico}/{(registro.anno_accademico + 1) % 100:02d}'
    reg.dump(registro, out, header=f'# Registro attivita\' didattiche GOMP, A.A. {year}\n'
                                   f'# Generato con `python -m gomp pull`. Una lezione e\' identificata da data + "dalle".\n\n')
    console.print(f'{len(registro.lezioni)} lessons written to {out}')
    for slot in skipped:
        console.print(f'[yellow]Skipped all-day slot[/yellow] {slot["DateFrom"][:10]}: '
                      f'{reg._short_tipo(slot.get("ActivityType"))}')


def _show(the_plan: reg.Plan) -> None:
    table = Table(show_lines=False)
    for column in ('', 'Data', 'Orario', 'Dettaglio'):
        table.add_column(column)
    marks = {'create': '[green]+[/green]', 'update': '[yellow]~[/yellow]',
             'unchanged': '[dim]=[/dim]', 'blocked': '[red]![/red]'}
    for action in the_plan.actions:
        lez = action.lezione
        if action.kind == 'create':
            detail = lez.descrizione[:70]
        elif action.kind == 'update':
            detail = '; '.join(f'{k}: {str(old)[:30]!r} -> {str(new)[:40]!r}' for k, (old, new) in action.changes.items())
        elif action.kind == 'blocked':
            detail = action.reason
        else:
            detail = ''
        table.add_row(marks[action.kind], f'{lez.data:%a %d/%m/%Y}', f'{lez.dalle}-{lez.alle}', detail)
    console.print(table)
    for slot in the_plan.only_on_gomp:
        start = from_wire(slot['DateFrom'])
        console.print(f'[cyan]Only on GOMP (left untouched):[/cyan] {start:%d/%m/%Y %H:%M} '
                      f'{(slot.get("Notes") or "")[:60]}')
    counts = {k: sum(a.kind == k for a in the_plan.actions) for k in marks}
    console.print(f'{counts["create"]} to create, {counts["update"]} to update, '
                  f'{counts["unchanged"]} unchanged, {counts["blocked"]} blocked.')


@cli.command()
@click.argument('file', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option('--save', is_flag=True, help='Actually write to GOMP. Without it, only show the plan.')
@click.pass_context
def apply(ctx: click.Context, file: Path, save: bool) -> None:
    """Create or update the lessons of FILE on GOMP. Never deletes anything."""
    registro = reg.load(file)
    client = _client(ctx)
    try:
        the_plan = reg.plan(client, registro)
    except GompError as exc:
        raise click.ClickException(str(exc)) from exc
    _show(the_plan)
    if not save:
        if the_plan.writes:
            console.print('Dry run: add --save to write.')
        return
    for action, warnings in reg.apply(client, the_plan):
        note = f' ({"; ".join(warnings)})' if warnings else ''
        console.print(f'saved {action.lezione.data:%d/%m/%Y} {action.lezione.dalle}{note}')


main = cli
