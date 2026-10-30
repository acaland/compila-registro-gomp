from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

import requests


GOMP_BASE = 'https://unict-segreteriecore.gomp.it'
API = f'{GOMP_BASE}/Professors/ActivityReport'
ROME = ZoneInfo('Europe/Rome')


class GompError(RuntimeError):
    """The register answered with success: false, or with something unexpected."""


class SessionExpired(GompError):
    """GOMP sent us to its login page instead of answering with JSON."""


def to_wire(value: datetime) -> str:
    """Local Rome time -> the UTC ISO string the web client sends (JSON.stringify of a Date)."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=ROME)
    return value.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')


def from_wire(value: str | None) -> datetime | None:
    """The register returns naive local times with 7 fractional digits: 2026-06-03T15:30:00.0000000."""
    if not value:
        return None
    return datetime.fromisoformat(value[:19])


class GompClient:
    """Thin wrapper over the JSON endpoints behind /Professors/ActivityReport.

    Every call is a POST with a JSON body, authenticated by the session cookie
    alone (no CSRF token). The client mirrors what activityReport.js does, so
    payloads stay byte-compatible with the web UI.
    """

    def __init__(self, session: requests.Session):
        self.session = session

    def _post(self, endpoint: str, body: dict[str, Any]) -> dict[str, Any]:
        response = self.session.post(
            f'{API}/{endpoint}',
            json=body,
            headers={'Accept': 'application/json'},
            timeout=60,
        )
        if '/Login' in response.url or 'json' not in response.headers.get('content-type', ''):
            raise SessionExpired('GOMP session expired: log in again.')
        response.raise_for_status()
        data = response.json()
        if not data.get('success', False):
            raise GompError(data.get('message') or f'{endpoint} failed.')
        return data

    def is_authenticated(self) -> bool:
        try:
            self.init()
        except SessionExpired:
            return False
        return True

    def init(self) -> dict[str, Any]:
        """Activity types (`types`), config, last saved item."""
        return self._post('Init', {})

    def get_data(self, date_from: date, date_to: date) -> dict[str, Any]:
        """Slots between two local dates, plus subtotals, periods and holidays."""
        return self._post('GetData', {
            'DateFrom': to_wire(datetime.combine(date_from, time())),
            'DateTo': to_wire(datetime.combine(date_to, time())),
            'CalendarMode': None,
        })

    def find_activities(self, at: datetime, text: str = '', only_mine: bool = True) -> list[dict[str, Any]]:
        """Teaching assignments usable on a given day (the `Details` of a slot)."""
        data = self._post('FindActivities', {
            'text': text,
            'FindOnlyProfessorActivty': only_mine,  # sic, as the server spells it
            'SelectedDateFromTheModal': to_wire(at),
        })
        return data.get('activities') or []

    def find_spaces(self, text: str) -> list[dict[str, Any]]:
        """Rooms whose name matches `text` (the UI requires at least 3 characters)."""
        return self._post('FindSpaces', {'text': text}).get('spaces') or []

    def save(self, item: dict[str, Any]) -> list[str]:
        """Create (no UID) or update (with UID) a slot. Returns the server warnings."""
        return self._post('Save', {'item': item}).get('warnings') or []

    def remove(self, item: dict[str, Any]) -> list[str]:
        return self._post('Remove', {'item': item}).get('warnings') or []
