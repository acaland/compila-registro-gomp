/*
 * Compila registro: bookmarklet for the unict GOMP teaching register.
 *
 * Runs inside https://unict-segreteriecore.gomp.it/Professors/ActivityReport,
 * with the teacher's own session, and talks to the same JSON endpoints the
 * page uses (Init, GetData, FindActivities, FindSpaces, Save). It never
 * deletes anything. See gomp/README.md for the API notes.
 */
(() => {
  'use strict';

  const VERSION = '0.1.0';
  const API = '/Professors/ActivityReport/';
  const DRAFT_KEY = 'gompRegistro.draft';

  if (!/gomp\.it$/.test(location.hostname) || !location.pathname.startsWith('/Professors/ActivityReport')) {
    alert('Apri prima il Registro attività didattiche su GOMP, poi clicca di nuovo il segnalibro.');
    return;
  }
  if (window.__gompRegistro) {
    window.__gompRegistro.toggle();
    return;
  }

  // ── dates ─────────────────────────────────────────────────────────────────
  // The page works in the browser's local time and sends Date objects, which
  // JSON turns into UTC. The server answers with naive local times.

  const pad = (n) => String(n).padStart(2, '0');
  const DAY_NAMES = ['Dom', 'Lun', 'Mar', 'Mer', 'Gio', 'Ven', 'Sab'];

  function parseWire(value) {
    if (!value) return null;
    const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(value);
    return m ? new Date(+m[1], m[2] - 1, +m[3], +m[4], +m[5]) : new Date(value);
  }
  const dayKey = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const slotKey = (d) => `${dayKey(d)} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  const itDate = (d) => `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()}`;
  const hhmm = (d) => `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  const midnight = (d, plusDays = 0) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + plusDays);

  // ── text helpers ──────────────────────────────────────────────────────────

  const norm = (s) => String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
  const tokens = (s) => norm(s).split(/[^a-z0-9]+/).filter(Boolean);
  const squash = (s) => String(s || '').replace(/\s+/g, ' ').trim();
  const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  // ── API ───────────────────────────────────────────────────────────────────

  async function post(endpoint, body) {
    const res = await fetch(API + endpoint, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (/\/Login/i.test(res.url) || !(res.headers.get('content-type') || '').includes('json')) {
      throw new Error('Sessione scaduta: ricarica la pagina e rientra nel registro.');
    }
    const data = await res.json();
    if (!data.success) throw new Error(data.message || `${endpoint} non riuscito.`);
    return data;
  }

  const api = {
    init: () => post('Init', {}),
    getData: (from, to) => post('GetData', { DateFrom: from, DateTo: to, CalendarMode: null }),
    findActivities: (at) =>
      post('FindActivities', { text: '', FindOnlyProfessorActivty: true, SelectedDateFromTheModal: at })
        .then((d) => d.activities || []),
    findSpaces: (text) => post('FindSpaces', { text }).then((d) => d.spaces || []),
    save: (item) => post('Save', { item }).then((d) => d.warnings || []),
  };

  // ── parsing the teacher's text ────────────────────────────────────────────
  //
  //   Insegnamento: 1001234            (codice o parte del nome)
  //   Aula: aula 3 edificio B (testo libero)
  //
  //   Sab 28/02/2026 10:00-13:00 aula magna
  //   Lezione I - descrizione, anche su piu' righe
  //
  // or cells pasted from a spreadsheet: Data, Dalle, Alle, Aula, Descrizione.

  const KEY_RE = /^\s*(insegnamento|aula|tipo)\s*:\s*(.*?)\s*(?:#.*)?$/i;
  const LESSON_RE = new RegExp(
    '^\\s*(?:[a-zàèéìòù]{3,}\\.?,?\\s+)?' +            // optional weekday
    '(\\d{1,2})[/.\\-](\\d{1,2})[/.\\-](\\d{4}|\\d{2})' + // date
    '\\s+(?:dalle\\s+)?(\\d{1,2})[:.](\\d{2})' +          // start
    '\\s*(?:-|–|—|alle)\\s*(\\d{1,2})[:.](\\d{2})' +      // end
    '\\s*[,;|]?\\s*(.*)$', 'i');                            // optional room

  function makeLesson(line, d, mo, y, h1, m1, h2, m2, aula, errors) {
    const year = y.length === 2 ? 2000 + +y : +y;
    const start = new Date(year, mo - 1, +d, +h1, +m1);
    const end = new Date(year, mo - 1, +d, +h2, +m2);
    if (start.getDate() !== +d || start.getMonth() !== mo - 1) {
      errors.push({ line, msg: `data inesistente: ${d}/${mo}/${y}` });
      return null;
    }
    if (+h1 > 23 || +m1 > 59 || +h2 > 23 || +m2 > 59 || end <= start) {
      errors.push({ line, msg: 'orario non valido: la fine deve seguire l\'inizio (es. 10:00-13:00)' });
      return null;
    }
    return { line, start, end, aula: squash(aula) || null, descr: '' };
  }

  function splitTsv(text) {
    // Spreadsheet copies quote cells containing tabs, quotes or newlines.
    const rows = [[]];
    let cell = '', quoted = false;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (quoted) {
        if (c === '"' && text[i + 1] === '"') { cell += '"'; i++; }
        else if (c === '"') quoted = false;
        else cell += c;
      } else if (c === '"' && cell === '') quoted = true;
      else if (c === '\t') { rows[rows.length - 1].push(cell); cell = ''; }
      else if (c === '\n') { rows[rows.length - 1].push(cell); cell = ''; rows.push([]); }
      else if (c !== '\r') cell += c;
    }
    rows[rows.length - 1].push(cell);
    return rows;
  }

  function parseTable(text, out) {
    const rows = splitTsv(text);
    let cols = null;
    rows.forEach((cells, i) => {
      const line = i + 1;
      if (cells.length === 1) {
        const key = KEY_RE.exec(cells[0]);
        if (key) out.defaults[key[1].toLowerCase()] = key[2];
        return;
      }
      if (cells.every((c) => !c.trim())) return;
      if (!cols && cells.some((c) => /^\s*data\s*$/i.test(c))) {
        cols = {};
        cells.forEach((c, j) => {
          const n = norm(c).trim();
          if (n === 'data') cols.data = j;
          else if (/^(dalle|inizio|ora inizio)$/.test(n)) cols.dalle = j;
          else if (/^(alle|fine|ora fine)$/.test(n)) cols.alle = j;
          else if (n === 'orario') cols.orario = j;
          else if (n === 'aula') cols.aula = j;
          else if (/^(descrizione|argomenti|programma|descrizione e\/o programma)$/.test(n)) cols.descr = j;
        });
        return;
      }
      const c = cols || { data: 0, dalle: 1, alle: 2, aula: 3, descr: 4 };
      const get = (k) => (c[k] === undefined ? '' : (cells[c[k]] || '').trim());
      const orario = get('orario') || `${get('dalle')}-${get('alle')}`;
      const head = LESSON_RE.exec(`${get('data')} ${orario}`);
      if (!head) {
        out.errors.push({ line, msg: `riga non riconosciuta: data "${get('data')}", orario "${orario}"` });
        return;
      }
      const lesson = makeLesson(line, head[1], head[2], head[3], head[4], head[5], head[6], head[7], get('aula'), out.errors);
      if (lesson) { lesson.descr = squash(get('descr')); out.lessons.push(lesson); }
    });
  }

  function parseText(text) {
    const out = { defaults: {}, lessons: [], errors: [] };
    const lines = text.split(/\r?\n/);
    if (lines.filter((l) => l.includes('\t')).length >= 1) {
      parseTable(text, out);
    } else {
      let current = null;
      lines.forEach((raw, i) => {
        const line = i + 1;
        if (!raw.trim() || /^\s*#/.test(raw)) return;
        const head = LESSON_RE.exec(raw);
        if (head) {
          current = makeLesson(line, head[1], head[2], head[3], head[4], head[5], head[6], head[7], head[8], out.errors);
          if (current) out.lessons.push(current);
          else current = { descr: '' }; // swallow the description of a rejected lesson
          return;
        }
        const key = !out.lessons.length && KEY_RE.exec(raw);
        if (key) { out.defaults[key[1].toLowerCase()] = key[2]; return; }
        if (current) { current.descr = squash(`${current.descr} ${raw}`); return; }
        if (!out.errors.some((e) => e.line === line)) {
          out.errors.push({ line, msg: 'riga non riconosciuta: prima delle lezioni sono ammesse solo "Insegnamento:", "Aula:" e "Tipo:"' });
        }
      });
    }
    const seen = new Map();
    for (const l of out.lessons) {
      const k = slotKey(l.start);
      if (seen.has(k)) out.errors.push({ line: l.line, msg: `stessa data e ora di inizio della riga ${seen.get(k)}` });
      else seen.set(k, l.line);
      if (!l.descr) out.errors.push({ line: l.line, msg: 'manca la descrizione della lezione' });
    }
    return out;
  }

  // ── resolving names to GOMP objects ───────────────────────────────────────

  const STOP = new Set(['aula', 'di', 'del', 'della', 'dei', 'degli', 'e', 'ed', 'il', 'la', 'lo', 'le', 'a', 'n', 'nr', 'num']);
  const spaceLabel = (s) => [s.Denominazione, s.ParentEdificio && s.ParentEdificio.Denominazione]
    .filter(Boolean).map((x) => x.trim()).join(', ');

  class Resolver {
    constructor() {
      this.spaces = new Map();
      this.activities = new Map();
      this.types = null;
    }

    // `current` is the room a slot already has: when the text is ambiguous
    // but includes it, keep it rather than complain.
    async space(query, current) {
      const key = norm(squash(query));
      if (!this.spaces.has(key)) this.spaces.set(key, this._space(query));
      const result = await this.spaces.get(key);
      if (result.hits.length === 1) return result.hits[0];
      const same = current && result.hits.find((s) => s.UID === current);
      if (same) return same;
      if (!result.hits.length) throw new Error(`aula "${query}" non trovata`);
      throw new Error(`aula "${query}" ambigua: ${result.hits.slice(0, 5).map(spaceLabel).join(' | ')}${result.hits.length > 5 ? ' …' : ''}`);
    }

    async _space(query) {
      const want = tokens(query).filter((t) => !STOP.has(t));
      if (!want.length) return { hits: [] };
      const terms = [squash(query), ...want.filter((t) => t.length >= 3 && !/^\d+$/.test(t))];
      const found = new Map();
      for (const term of new Set(terms)) {
        for (const s of await api.findSpaces(term)) found.set(s.UID, s);
      }
      let hits = [...found.values()].filter((s) => {
        const hay = tokens(spaceLabel(s));
        return want.every((t) => hay.some((h) => (/^\d+$/.test(t) ? h === t : h.startsWith(t))));
      });
      if (hits.length > 1) {
        const live = hits.filter((s) => !/da rimuovere/i.test(s.Denominazione || ''));
        if (live.length) hits = live;
        const exact = hits.filter((s) => [s.Denominazione, spaceLabel(s)].some((x) => norm(squash(x)) === norm(squash(query))));
        if (exact.length === 1) hits = exact;
      }
      return { hits };
    }

    async activity(spec, day) {
      const key = dayKey(day);
      if (!this.activities.has(key)) this.activities.set(key, api.findActivities(new Date(day.getFullYear(), day.getMonth(), day.getDate(), 9)));
      const all = await this.activities.get(key);
      const label = (a) => `[${a.ActivityCode}] ${a.ActivityName} (${a.CourseName || a.CourseCode || ''})`;
      let hits = all;
      if (spec) {
        const s = squash(spec);
        hits = /^\d+$/.test(s)
          ? all.filter((a) => a.ActivityCode === s)
          : all.filter((a) => tokens(s).every((t) => tokens(`${a.ActivityName} ${a.CourseName} ${a.CourseCode}`).some((h) => h.startsWith(t))));
      }
      const byCode = new Map(hits.map((a) => [a.ActivityCode, a]));
      if (byCode.size === 1) return [...byCode.values()][0];
      if (!byCode.size) {
        throw new Error(spec
          ? `insegnamento "${spec}" non disponibile il ${itDate(day)}`
          : `nessun insegnamento disponibile il ${itDate(day)}`);
      }
      throw new Error(`${spec ? `insegnamento "${spec}" ambiguo` : 'hai più insegnamenti: aggiungi "Insegnamento: codice"'}: ${[...byCode.values()].map(label).join(' | ')}`);
    }

    async type(spec) {
      if (!this.types) this.types = (await api.init()).types || [];
      const want = norm(squash(spec || 'Didattica frontale'));
      const t = this.types.find((x) => x.NeedFromTo && norm(x.Description).startsWith(want));
      if (!t) throw new Error(`tipo di attività "${spec}" non trovato`);
      return t;
    }
  }

  // ── plan & publish ────────────────────────────────────────────────────────

  const shortType = (t) => ((t && t.Description) || '').split(' - ')[0].trim();
  const codes = (slot) => (slot.Details || []).map((d) => d.ActivityCode).filter(Boolean);

  function lockedBySignature(day, signatures) {
    return (signatures || []).some((sig) => {
      const lower = Object.fromEntries(Object.entries(sig).map(([k, v]) => [k.toLowerCase(), v]));
      const from = parseWire(lower.datefrom), to = parseWire(lower.dateto);
      return from && to && midnight(from) <= day && day <= midnight(to);
    });
  }

  async function makePlan(parsed) {
    const lessons = [...parsed.lessons].sort((a, b) => a.start - b.start);
    const first = midnight(lessons[0].start), last = midnight(lessons[lessons.length - 1].start, 1);
    const data = await api.getData(first, last);
    const periods = data.periods || [data.period];
    const existing = new Map((data.activities || []).map((s) => [slotKey(parseWire(s.DateFrom)), s]));
    const resolver = new Resolver();
    const now = new Date();
    const d = parsed.defaults;
    const actions = [];

    for (const lesson of lessons) {
      const day = midnight(lesson.start);
      const action = { lesson, kind: 'unchanged', changes: [], item: null, reason: '' };
      actions.push(action);
      const period = periods.find((p) => p && midnight(parseWire(p.DateFrom)) <= day && day <= midnight(parseWire(p.DateTo)));
      const enabledTo = period && parseWire(period.EnabledTo);
      const enabledFrom = period && parseWire(period.EnabledFrom);
      if (!period) { action.kind = 'blocked'; action.reason = 'data fuori dagli anni accademici gestiti'; continue; }
      if ((enabledTo && now > midnight(enabledTo, 1)) || (enabledFrom && now < enabledFrom)) {
        action.kind = 'blocked';
        action.reason = `A.A. ${period.Description} modificabile ${enabledFrom ? `dal ${itDate(enabledFrom)} ` : ''}al ${itDate(enabledTo)}`;
        continue;
      }
      if (lockedBySignature(day, data.signatures)) { action.kind = 'blocked'; action.reason = 'mese già firmato'; continue; }

      const aulaSpec = lesson.aula || d.aula;
      const slot = existing.get(slotKey(lesson.start));
      try {
        if (!slot) {
          if (!aulaSpec) throw new Error('manca l\'aula (riga "Aula:" in cima o dopo l\'orario)');
          const [type, space, activity] = await Promise.all([
            resolver.type(d.tipo), resolver.space(aulaSpec), resolver.activity(d.insegnamento, day),
          ]);
          action.kind = 'create';
          action.changes.push(`${spaceLabel(space)} · [${activity.ActivityCode}] ${activity.ActivityName}`);
          action.item = {
            DateFrom: lesson.start, DateTo: lesson.end,
            ActivityTypeUID: type.UID, ActivityType: type,
            SpaceUID: space.UID, Space: space,
            Details: [activity], Notes: lesson.descr, CustomActivity: null, CustomSpace: null,
          };
          continue;
        }
        existing.delete(slotKey(lesson.start));
        const item = { ...slot, DateFrom: lesson.start, DateTo: lesson.end };
        const oldEnd = parseWire(slot.DateTo);
        if (!oldEnd || oldEnd.getTime() !== lesson.end.getTime()) action.changes.push(`fine ${oldEnd ? hhmm(oldEnd) : '—'} → ${hhmm(lesson.end)}`);
        if (squash(slot.Notes) !== squash(lesson.descr)) {
          action.changes.push(slot.Notes ? 'descrizione modificata' : 'descrizione aggiunta');
          item.Notes = lesson.descr;
        }
        if (aulaSpec) {
          const space = await resolver.space(aulaSpec, slot.SpaceUID);
          if (space.UID !== slot.SpaceUID) {
            action.changes.push(`aula ${slot.Space ? spaceLabel(slot.Space) : '—'} → ${spaceLabel(space)}`);
            Object.assign(item, { Space: space, SpaceUID: space.UID, CustomSpace: null });
          }
        }
        if (d.insegnamento) {
          const activity = await resolver.activity(d.insegnamento, day);
          if (!codes(slot).includes(activity.ActivityCode)) {
            action.changes.push(`insegnamento → ${activity.ActivityCode}`);
            Object.assign(item, { Details: [activity], CustomActivity: null });
          }
        }
        if (d.tipo && !norm(slot.ActivityType && slot.ActivityType.Description).startsWith(norm(d.tipo))) {
          const type = await resolver.type(d.tipo);
          action.changes.push(`tipo ${shortType(slot.ActivityType)} → ${shortType(type)}`);
          Object.assign(item, { ActivityType: type, ActivityTypeUID: type.UID });
        }
        if (action.changes.length) { action.kind = 'update'; action.item = item; }
      } catch (err) {
        action.kind = 'blocked';
        action.reason = err.message;
      }
    }
    const onlyOnGomp = [...existing.values()].sort((a, b) => parseWire(a.DateFrom) - parseWire(b.DateFrom));
    return { actions, onlyOnGomp };
  }

  // ── reading the register back as text ─────────────────────────────────────

  async function registerAsText(period) {
    const from = midnight(parseWire(period.DateFrom)), to = midnight(parseWire(period.DateTo), 1);
    const slots = ((await api.getData(from, to)).activities || [])
      .filter((s) => s.DateTo)
      .sort((a, b) => parseWire(a.DateFrom) - parseWire(b.DateFrom));
    const mostCommon = (values) => {
      const counts = new Map();
      values.filter(Boolean).forEach((v) => counts.set(v, (counts.get(v) || 0) + 1));
      return [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] || null;
    };
    const room = (s) => (s.Space ? spaceLabel(s.Space) : s.CustomSpace || null);
    const code = mostCommon(slots.map((s) => codes(s)[0]));
    const aula = mostCommon(slots.map(room));
    const names = new Map(slots.flatMap((s) => (s.Details || []).map((x) => [x.ActivityCode, x.ActivityName])));
    const out = [
      `# Registro A.A. ${period.Description}, letto da GOMP il ${itDate(new Date())}`,
      `# Una lezione: riga con data, orario ed eventuale aula, poi la descrizione.`,
      '',
      `Insegnamento: ${code || ''}${code && names.get(code) ? `   # ${names.get(code)}` : ''}`,
      `Aula: ${aula || ''}`,
      '',
    ];
    for (const s of slots) {
      const start = parseWire(s.DateFrom), end = parseWire(s.DateTo);
      const other = room(s) && room(s) !== aula ? ` ${/^aula\b/i.test(room(s)) ? '' : 'aula '}${room(s)}` : '';
      out.push(`${DAY_NAMES[start.getDay()]} ${itDate(start)} ${hhmm(start)}-${hhmm(end)}${other}`);
      out.push(squash(s.Notes) || '(senza descrizione)', '');
    }
    return out.join('\n');
  }

  // ── panel ─────────────────────────────────────────────────────────────────

  const host = document.createElement('div');
  host.id = 'gomp-registro-panel';
  document.body.appendChild(host);
  const root = host.attachShadow({ mode: 'open' });
  root.innerHTML = `
    <style>
      :host { all: initial; }
      .panel { position: fixed; top: 0; right: 0; bottom: 0; width: min(560px, 100vw); z-index: 2147483000;
        background: #fff; color: #1f2933; box-shadow: -4px 0 24px rgba(0,0,0,.18); display: flex; flex-direction: column;
        font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
      .panel[hidden] { display: none; }
      header { display: flex; align-items: center; gap: 8px; padding: 12px 16px; background: #1e3a8a; color: #fff; }
      header h1 { font-size: 16px; margin: 0; flex: 1; }
      header small { opacity: .7; }
      header button { background: none; border: 0; color: #fff; font-size: 20px; cursor: pointer; }
      .body { flex: 1; overflow: auto; padding: 12px 16px; display: flex; flex-direction: column; gap: 10px; }
      textarea { width: 100%; box-sizing: border-box; min-height: 260px; flex: none; resize: vertical; padding: 8px;
        font: 13px/1.45 ui-monospace, Menlo, Consolas, monospace; border: 1px solid #cbd2d9; border-radius: 6px; }
      .row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
      button.btn { padding: 7px 14px; border-radius: 6px; border: 1px solid #cbd2d9; background: #f5f7fa; cursor: pointer; font: inherit; }
      button.primary { background: #1e3a8a; border-color: #1e3a8a; color: #fff; }
      button.publish { background: #15803d; border-color: #15803d; color: #fff; }
      button:disabled { opacity: .45; cursor: default; }
      select { padding: 6px; border-radius: 6px; border: 1px solid #cbd2d9; font: inherit; }
      details { font-size: 13px; color: #52606d; }
      details pre { background: #f5f7fa; padding: 8px; border-radius: 6px; white-space: pre-wrap; }
      .msg { padding: 8px 10px; border-radius: 6px; }
      .msg.err { background: #fde8e8; color: #9b1c1c; }
      .msg.ok { background: #e6f4ea; color: #14532d; }
      .msg.info { background: #eef2ff; color: #1e3a8a; }
      table { border-collapse: collapse; width: 100%; font-size: 13px; }
      td { border-top: 1px solid #e4e7eb; padding: 5px 4px; vertical-align: top; }
      td.k { width: 18px; font-weight: 700; text-align: center; }
      .create { color: #15803d; } .update { color: #b45309; } .unchanged { color: #9aa5b1; } .blocked { color: #b91c1c; }
      .nowrap { white-space: nowrap; }
    </style>
    <div class="panel">
      <header><h1>Compila registro</h1><small>v${VERSION}</small><button class="close" title="Chiudi">×</button></header>
      <div class="body">
        <details>
          <summary>Come si scrive</summary>
          <pre>Insegnamento: 1001234          (codice o parte del nome; facoltativo se ne hai uno solo)
Aula: aula 3 edificio B (testo libero, basta che individui l'aula)

Sab 28/02/2026 10:00-13:00 aula magna
Lezione I - Introduzione al corso: presentazione...

28/05/26 11:00-14:00
Lezione II - Introduzione a SQL: ...</pre>
          Una lezione è identificata da data e ora di inizio: se nel registro esiste già viene aggiornata,
          altrimenti viene creata. Nulla viene mai cancellato. Puoi anche incollare celle da Excel
          con colonne Data, Dalle, Alle, Aula, Descrizione.
        </details>
        <div class="row">
          <select class="period"><option>Anno accademico…</option></select>
          <button class="btn load">Carica dal registro</button>
        </div>
        <textarea spellcheck="false" placeholder="Scrivi o incolla qui le lezioni, oppure usa «Carica dal registro»."></textarea>
        <div class="row">
          <button class="btn primary check">Controlla</button>
          <button class="btn publish" disabled>Pubblica</button>
        </div>
        <div class="out"></div>
      </div>
    </div>`;

  const $ = (sel) => root.querySelector(sel);
  const panel = $('.panel'), text = $('textarea'), out = $('.out');
  const checkBtn = $('.check'), publishBtn = $('.publish'), loadBtn = $('.load'), periodSel = $('.period');
  let lastPlan = null, checkedText = null, periods = [];

  try { text.value = localStorage.getItem(DRAFT_KEY) || ''; } catch (e) { /* storage unavailable */ }

  const show = (html) => { out.innerHTML = html; };
  const busy = () => [checkBtn, loadBtn, publishBtn].forEach((b) => { b.disabled = true; });
  const refreshButtons = () => {
    checkBtn.disabled = loadBtn.disabled = false;
    publishBtn.disabled = !(lastPlan && checkedText === text.value && lastPlan.writes.length);
    publishBtn.textContent = lastPlan && lastPlan.writes.length ? `Pubblica ${lastPlan.writes.length} ${lastPlan.writes.length === 1 ? 'modifica' : 'modifiche'}` : 'Pubblica';
  };

  text.addEventListener('input', () => {
    try { localStorage.setItem(DRAFT_KEY, text.value); } catch (e) { /* storage unavailable */ }
    refreshButtons();
  });

  async function loadPeriods() {
    const today = midnight(new Date());
    const data = await api.getData(today, midnight(today, 1));
    periods = (data.periods || [data.period]).filter(Boolean)
      .sort((a, b) => parseWire(b.DateFrom) - parseWire(a.DateFrom));
    periodSel.innerHTML = periods.map((p, i) =>
      `<option value="${i}" ${data.period && p.UID === data.period.UID ? 'selected' : ''}>A.A. ${esc(p.Description)}</option>`).join('');
  }

  const MARK = { create: '+', update: '~', unchanged: '=', blocked: '!' };

  function renderPlan(plan) {
    const count = (k) => plan.actions.filter((a) => a.kind === k).length;
    const rows = plan.actions.map((a) => {
      const l = a.lesson;
      const detail = a.kind === 'blocked' ? a.reason
        : a.kind === 'create' ? `nuova · ${a.changes.join('; ')}`
        : a.changes.join('; ');
      return `<tr class="${a.kind}"><td class="k">${MARK[a.kind]}</td>
        <td class="nowrap">${DAY_NAMES[l.start.getDay()]} ${itDate(l.start)}<br>${hhmm(l.start)}-${hhmm(l.end)}</td>
        <td>${esc(detail)}${a.kind !== 'blocked' ? `<br><span class="unchanged">${esc(l.descr.slice(0, 90))}${l.descr.length > 90 ? '…' : ''}</span>` : ''}</td></tr>`;
    }).join('');
    const extra = plan.onlyOnGomp.length
      ? `<div class="msg info">Nel registro ci sono anche ${plan.onlyOnGomp.length} slot non presenti nel testo, che restano come sono: ${
          plan.onlyOnGomp.map((s) => `${itDate(parseWire(s.DateFrom))} ${hhmm(parseWire(s.DateFrom))}`).join(', ')}.</div>` : '';
    return `<div class="msg ${count('blocked') ? 'err' : 'ok'}">${count('create')} da creare, ${count('update')} da aggiornare,
      ${count('unchanged')} invariate${count('blocked') ? `, <b>${count('blocked')} con problemi</b>` : ''}.
      ${count('blocked') && plan.writes.length ? '<br>«Pubblica» salva solo le righe senza problemi.' : ''}</div>
      <table>${rows}</table>${extra}`;
  }

  checkBtn.addEventListener('click', async () => {
    lastPlan = null;
    const parsed = parseText(text.value);
    if (parsed.errors.length) {
      show(`<div class="msg err"><b>Da correggere nel testo:</b><br>${parsed.errors
        .sort((a, b) => a.line - b.line).map((e) => `riga ${e.line}: ${esc(e.msg)}`).join('<br>')}</div>`);
      refreshButtons();
      return;
    }
    if (!parsed.lessons.length) { show('<div class="msg err">Nessuna lezione trovata nel testo.</div>'); return; }
    busy();
    show('<div class="msg info">Controllo in corso…</div>');
    try {
      const plan = await makePlan(parsed);
      plan.writes = plan.actions.filter((a) => a.kind === 'create' || a.kind === 'update');
      lastPlan = plan;
      checkedText = text.value;
      show(renderPlan(plan));
    } catch (err) {
      show(`<div class="msg err">${esc(err.message)}</div>`);
    }
    refreshButtons();
  });

  publishBtn.addEventListener('click', async () => {
    if (!lastPlan || checkedText !== text.value) return;
    busy();
    const lines = [];
    let failed = 0;
    for (const a of lastPlan.writes) {
      const when = `${itDate(a.lesson.start)} ${hhmm(a.lesson.start)}`;
      try {
        const warnings = await api.save(a.item);
        lines.push(`✓ ${when}${warnings.length ? ` <span class="unchanged">(${esc(warnings.join('; '))})</span>` : ''}`);
      } catch (err) {
        failed++;
        lines.push(`<span class="blocked">✗ ${when}: ${esc(err.message)}</span>`);
      }
      show(`<div class="msg info">${lines.join('<br>')}</div>`);
    }
    show(`<div class="msg ${failed ? 'err' : 'ok'}">${lines.join('<br>')}</div>
      <div class="row"><button class="btn reload">Ricarica la pagina per vedere il calendario aggiornato</button></div>`);
    $('.reload').addEventListener('click', () => location.reload());
    lastPlan = null;
    refreshButtons();
  });

  loadBtn.addEventListener('click', async () => {
    const period = periods[+periodSel.value];
    if (!period) return;
    if (text.value.trim() && loadBtn.dataset.confirm !== '1') {
      loadBtn.dataset.confirm = '1';
      loadBtn.textContent = 'Sostituire il testo attuale? Clicca di nuovo';
      setTimeout(() => { loadBtn.dataset.confirm = ''; loadBtn.textContent = 'Carica dal registro'; }, 5000);
      return;
    }
    loadBtn.dataset.confirm = '';
    loadBtn.textContent = 'Carica dal registro';
    busy();
    try {
      text.value = await registerAsText(period);
      try { localStorage.setItem(DRAFT_KEY, text.value); } catch (e) { /* storage unavailable */ }
      show(`<div class="msg info">Caricate le lezioni dell'A.A. ${esc(period.Description)}. Modifica il testo e premi «Controlla».</div>`);
    } catch (err) {
      show(`<div class="msg err">${esc(err.message)}</div>`);
    }
    lastPlan = null;
    refreshButtons();
  });

  $('.close').addEventListener('click', () => { panel.hidden = true; });

  window.__gompRegistro = {
    version: VERSION,
    toggle() { panel.hidden = !panel.hidden; },
    parseText, // exposed for testing
  };

  loadPeriods().catch((err) => show(`<div class="msg err">${esc(err.message)}</div>`));
})();
