from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator
import yaml

from .client import GompClient, GompError, from_wire, to_wire


DEFAULT_TIPO = 'Didattica frontale'


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Lezione(StrictModel):
    data: date
    dalle: str
    alle: str
    descrizione: str = ''
    # Per-lesson overrides of the register-wide defaults below.
    aula: str | None = None
    insegnamento: str | None = None
    tipo: str | None = None

    @field_validator('dalle', 'alle', mode='before')
    @classmethod
    def _sexagesimal(cls, value: Any) -> Any:
        # YAML 1.1 reads an unquoted 10:30 as the base-60 integer 630.
        return f'{value // 60:02d}:{value % 60:02d}' if isinstance(value, int) else value

    @field_validator('dalle', 'alle')
    @classmethod
    def _hhmm(cls, value: str) -> str:
        if not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', value):
            raise ValueError(f'expected HH:MM, got {value!r}')
        return value

    @model_validator(mode='after')
    def _order(self) -> 'Lezione':
        if self.alle <= self.dalle:
            raise ValueError(f'lesson of {self.data}: "alle" ({self.alle}) must follow "dalle" ({self.dalle}).')
        return self

    @property
    def start(self) -> datetime:
        return datetime.combine(self.data, time.fromisoformat(self.dalle))

    @property
    def end(self) -> datetime:
        return datetime.combine(self.data, time.fromisoformat(self.alle))


class Registro(StrictModel):
    """One teacher's register for one academic year, as kept in a YAML file.

    `insegnamento` is the GOMP activity code (e.g. "1001234"), `aula` the room
    name as GOMP spells it, `tipo` the start of the activity type description.
    A lesson is identified by its date and start time.
    """

    anno_accademico: int
    insegnamento: str
    aula: str | None = None
    tipo: str = DEFAULT_TIPO
    lezioni: list[Lezione]

    @model_validator(mode='after')
    def _unique(self) -> 'Registro':
        seen = Counter((lez.data, lez.dalle) for lez in self.lezioni)
        duplicates = [f'{d} {h}' for (d, h), n in seen.items() if n > 1]
        if duplicates:
            raise ValueError(f'two lessons start at the same time: {duplicates}')
        return self

    def aula_of(self, lez: Lezione) -> str | None:
        return lez.aula or self.aula

    def insegnamento_of(self, lez: Lezione) -> str:
        return lez.insegnamento or self.insegnamento

    def tipo_of(self, lez: Lezione) -> str:
        return lez.tipo or self.tipo


# ── YAML ────────────────────────────────────────────────────────────────────

class _Folded(str):
    pass


yaml.SafeDumper.add_representer(
    _Folded, lambda dumper, value: dumper.represent_scalar('tag:yaml.org,2002:str', value, style='>')
)


def load(path: Path) -> Registro:
    return Registro.model_validate(yaml.safe_load(path.read_text()))


def dump(registro: Registro, path: Path, header: str = '') -> None:
    data = registro.model_dump(exclude_none=True)
    for lez in data['lezioni']:
        if len(lez.get('descrizione', '')) > 60:
            lez['descrizione'] = _Folded(lez['descrizione'])
    text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=90)
    path.write_text(header + text)


# ── reading what GOMP holds ─────────────────────────────────────────────────

def _short_tipo(activity_type: dict[str, Any] | None) -> str:
    return (activity_type or {}).get('Description', '').split(' - ')[0].strip()


def _space_name(slot: dict[str, Any]) -> str | None:
    space = slot.get('Space') or {}
    return space.get('Denominazione') or slot.get('CustomSpace')


def _activity_codes(slot: dict[str, Any]) -> list[str]:
    return [d.get('ActivityCode') for d in (slot.get('Details') or []) if d.get('ActivityCode')]


def _period(client: GompClient, anno: int | None) -> dict[str, Any]:
    today = date.today()
    probe = client.get_data(today, today + timedelta(days=1))
    if anno is None:
        return probe['period']
    for period in probe.get('periods') or []:
        if period.get('AcademicYear') == anno:
            return period
    raise GompError(f'academic year {anno}/{anno + 1 - 2000:02d} not found on GOMP.')


def _slots_in(client: GompClient, period: dict[str, Any]) -> list[dict[str, Any]]:
    start = from_wire(period['DateFrom']).date()
    end = from_wire(period['DateTo']).date() + timedelta(days=1)
    slots = client.get_data(start, end).get('activities') or []
    return sorted(slots, key=lambda s: s['DateFrom'])


def pull(client: GompClient, anno: int | None = None) -> tuple[Registro, list[dict[str, Any]]]:
    """The register of an academic year as a Registro, plus the slots it cannot express.

    Defaults (insegnamento, aula, tipo) are the most common values; lessons
    that differ carry their own override. Slots without an end time (all-day
    activities) are returned apart.
    """
    period = _period(client, anno)
    slots = _slots_in(client, period)
    timed = [s for s in slots if s.get('DateTo')]
    skipped = [s for s in slots if not s.get('DateTo')]

    def most_common(values: list[Any]) -> Any:
        values = [v for v in values if v]
        return Counter(values).most_common(1)[0][0] if values else None

    insegnamento = most_common([(_activity_codes(s) or [None])[0] for s in timed]) or ''
    aula = most_common([_space_name(s) for s in timed])
    tipo = most_common([_short_tipo(s.get('ActivityType')) for s in timed]) or DEFAULT_TIPO

    lezioni = []
    for slot in timed:
        start, end = from_wire(slot['DateFrom']), from_wire(slot['DateTo'])
        code = (_activity_codes(slot) or [None])[0]
        lezioni.append(Lezione(
            data=start.date(),
            dalle=start.strftime('%H:%M'),
            alle=end.strftime('%H:%M'),
            descrizione=(slot.get('Notes') or '').strip(),
            aula=None if _space_name(slot) == aula else _space_name(slot),
            insegnamento=None if code == insegnamento else code,
            tipo=None if _short_tipo(slot.get('ActivityType')) == tipo else _short_tipo(slot.get('ActivityType')),
        ))
    registro = Registro(anno_accademico=period['AcademicYear'], insegnamento=insegnamento,
                        aula=aula, tipo=tipo, lezioni=lezioni)
    return registro, skipped


# ── plan / apply ────────────────────────────────────────────────────────────

Kind = Literal['create', 'update', 'unchanged', 'blocked']


@dataclass
class Action:
    kind: Kind
    lezione: Lezione
    changes: dict[str, tuple[Any, Any]] = field(default_factory=dict)
    reason: str = ''
    item: dict[str, Any] | None = None  # payload for Save, ready to send


@dataclass
class Plan:
    actions: list[Action]
    only_on_gomp: list[dict[str, Any]]  # slots GOMP has and the file does not; never deleted

    @property
    def writes(self) -> list[Action]:
        return [a for a in self.actions if a.kind in ('create', 'update')]


class _Resolver:
    """Looks up GOMP objects by the human names used in the YAML, with caching."""

    def __init__(self, client: GompClient):
        self.client = client
        self._types: list[dict[str, Any]] | None = None
        self._spaces: dict[str, dict[str, Any]] = {}
        self._activities: dict[tuple[str, date], list[dict[str, Any]]] = {}

    def activity_type(self, tipo: str) -> dict[str, Any]:
        if self._types is None:
            self._types = self.client.init().get('types') or []
        for t in self._types:
            if t.get('NeedFromTo') and t.get('Description', '').lower().startswith(tipo.lower()):
                return t
        raise GompError(f'no timed activity type starts with {tipo!r}.')

    def space(self, name: str) -> dict[str, Any]:
        if name not in self._spaces:
            wanted = name.strip().lower()
            for query in (name, name.split(' - ')[0]):
                match = next((s for s in self.client.find_spaces(query)
                              if (s.get('Denominazione') or '').strip().lower() == wanted), None)
                if match:
                    self._spaces[name] = match
                    break
            else:
                raise GompError(f'room {name!r} not found on GOMP.')
        return self._spaces[name]

    def details(self, code: str, at: datetime) -> list[dict[str, Any]]:
        key = (code, at.date())
        if key not in self._activities:
            found = [a for a in self.client.find_activities(at) if a.get('ActivityCode') == code]
            if not found:
                raise GompError(f'teaching {code} is not assignable on {at.date()}.')
            self._activities[key] = found[:1]
        return self._activities[key]


def _locked(day: date, signatures: list[dict[str, Any]]) -> bool:
    """A month already signed off cannot be edited."""
    for sig in signatures or []:
        lower = {k.lower(): v for k, v in sig.items()}
        start, end = from_wire(lower.get('datefrom')), from_wire(lower.get('dateto'))
        if start and end and start.date() <= day <= end.date():
            return True
    return False


def plan(client: GompClient, registro: Registro, now: datetime | None = None) -> Plan:
    now = now or datetime.now()
    period = _period(client, registro.anno_accademico)
    data_from, data_to = from_wire(period['DateFrom']).date(), from_wire(period['DateTo']).date()
    enabled_to = from_wire(period.get('EnabledTo'))
    window = client.get_data(data_from, data_to + timedelta(days=1))
    slots = window.get('activities') or []
    by_start = {from_wire(s['DateFrom']): s for s in slots}
    resolver = _Resolver(client)

    actions: list[Action] = []
    for lez in sorted(registro.lezioni, key=lambda x: x.start):
        existing = by_start.pop(lez.start, None)  # mentioned by the file, whatever happens below
        if not data_from <= lez.data <= data_to:
            actions.append(Action('blocked', lez, reason=f'outside academic year {period.get("Description")}'))
            continue
        if enabled_to and now > enabled_to + timedelta(days=1):
            actions.append(Action('blocked', lez, reason=f'register closed on {enabled_to.date()}'))
            continue
        if (existing and existing.get('SignatureUID')) or _locked(lez.data, window.get('signatures')):
            actions.append(Action('blocked', lez, reason='period already signed off'))
            continue

        aula, code, tipo = registro.aula_of(lez), registro.insegnamento_of(lez), registro.tipo_of(lez)
        try:
            if existing is None:
                if aula is None:
                    raise GompError('no room given (aula)')
                activity_type = resolver.activity_type(tipo)
                space = resolver.space(aula)
                item = {
                    'DateFrom': to_wire(lez.start), 'DateTo': to_wire(lez.end),
                    'ActivityTypeUID': activity_type['UID'], 'ActivityType': activity_type,
                    'SpaceUID': space['UID'], 'Space': space,
                    'Details': resolver.details(code, lez.start),
                    'Notes': lez.descrizione, 'CustomActivity': None, 'CustomSpace': None,
                }
                actions.append(Action('create', lez, item=item))
                continue

            changes: dict[str, tuple[Any, Any]] = {}
            item = dict(existing)
            item['DateFrom'] = to_wire(lez.start)
            old_end = from_wire(existing.get('DateTo'))
            if old_end != lez.end:
                changes['alle'] = (old_end.strftime('%H:%M') if old_end else None, lez.alle)
            item['DateTo'] = to_wire(lez.end)
            if (existing.get('Notes') or '').strip() != lez.descrizione.strip():
                changes['descrizione'] = (existing.get('Notes') or '', lez.descrizione)
                item['Notes'] = lez.descrizione
            if aula and _space_name(existing) != aula:
                changes['aula'] = (_space_name(existing), aula)
                space = resolver.space(aula)
                item.update({'Space': space, 'SpaceUID': space['UID'], 'CustomSpace': None})
            if code not in _activity_codes(existing):
                changes['insegnamento'] = (', '.join(_activity_codes(existing)), code)
                item.update({'Details': resolver.details(code, lez.start), 'CustomActivity': None})
            if _short_tipo(existing.get('ActivityType')).lower() != tipo.lower():
                changes['tipo'] = (_short_tipo(existing.get('ActivityType')), tipo)
                activity_type = resolver.activity_type(tipo)
                item.update({'ActivityType': activity_type, 'ActivityTypeUID': activity_type['UID']})
            actions.append(Action('update' if changes else 'unchanged', lez, changes=changes, item=item))
        except GompError as exc:
            actions.append(Action('blocked', lez, reason=str(exc)))

    return Plan(actions, sorted(by_start.values(), key=lambda s: s['DateFrom']))


def apply(client: GompClient, the_plan: Plan) -> list[tuple[Action, list[str]]]:
    """Send every create/update. Returns each action with the server warnings."""
    return [(action, client.save(action.item)) for action in the_plan.writes]
