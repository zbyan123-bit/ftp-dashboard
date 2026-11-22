"""Build index.html from template.html and data/*.json.

Run:  python3 build.py
Daily inputs (appended by the morning check-in): data/rides.json, data/whoop.json, data/week.json.
Everything in data/static.json is a snapshot from 20 Nov 2026 and is not recomputed here.
"""
import json, datetime as dt, pathlib

ROOT = pathlib.Path(__file__).parent
FTP = 255  # working FTP in W. Change here when FTP changes.
D = dt.date.fromisoformat
load = lambda f: json.loads((ROOT / 'data' / f).read_text(encoding='utf-8'))

static = load('static.json')
base = load('fitness_base.json')
rides = sorted(load('rides.json'), key=lambda r: r['date'])
whoop = sorted(load('whoop.json'), key=lambda r: r['date'])
week = sorted(load('week.json'), key=lambda r: r['date'])


def tss(r):
    np_ = r.get('np') or r.get('avg_w')
    return r['moving_h'] * (np_ / FTP) ** 2 * 100


# ---- daily load per date (rides after the base series)
day_load, day_rides = {}, {}
for r in rides:
    day_load[r['date']] = day_load.get(r['date'], 0) + tss(r)
    day_rides.setdefault(r['date'], []).append(r)

# ---- as-of date: latest ride or WHOOP morning
asof = max([base[-1]['date']] + [r['date'] for r in rides] + [w['date'] for w in whoop])

# ---- extend fitness (CTL 42 d, ATL 7 d)
fd = [dict(r) for r in base]
c, a = fd[-1]['ctl'], fd[-1]['atl']
day = D(fd[-1]['date']) + dt.timedelta(1)
while day <= D(asof):
    ds = day.isoformat(); l = day_load.get(ds, 0.0)
    c += (l - c) / 42; a += (l - a) / 7
    fd.append(dict(date=ds, load=round(l, 1), ctl=round(c, 1), atl=round(a, 1), tsb=round(c - a, 1)))
    day += dt.timedelta(1)
fdm = {r['date']: r for r in fd}

# ---- WHOOP: fill load of the day before
for w in whoop:
    if w.get('load_day_before') is None:
        prev = (D(w['date']) - dt.timedelta(1)).isoformat()
        w['load_day_before'] = round(fdm[prev]['load']) if prev in fdm else None

# ---- week: fill actuals from rides for dates after 20 Nov
def hm(h):
    m = round(h * 60); return f'{m // 60}:{m % 60:02d}'

seen = {r['date'] for r in week}
for d in day_rides:  # rides on dates with no plan row
    if d not in seen and d > '2026-11-20':
        week.append(dict(date=d, dow=D(d).strftime('%a'), type='ride', plan='(not in plan)', planned_h_max=0,
                         indoor=False, actual_h=None, np=None, max_w=None, tss=None, actual='', flags='', status='upcoming'))
week.sort(key=lambda r: r['date'])
for r in week:
    d = r['date']
    if d <= '2026-11-20' or d > asof:
        continue
    rs = day_rides.get(d, [])
    if not rs:
        if d < asof or (d == asof and any(w['date'] > d for w in whoop)):
            r.update(actual_h=0, np=None, max_w=None, tss=None, actual='No ride', flags='',
                     status='on plan' if r['type'] == 'rest' else 'skipped')
        continue
    h = sum(x['moving_h'] for x in rs); t = sum(tss(x) for x in rs)
    np_ = round((sum(x['moving_h'] * (x.get('np') or x['avg_w']) ** 4 for x in rs) / h) ** 0.25)
    mw = max((x.get('max_w') or 0) for x in rs) or None
    ind = all(x.get('indoor') for x in rs)
    flags = []
    if r['type'] == 'rest': flags.append('rest day ridden')
    if r['planned_h_max'] and h > r['planned_h_max'] + 0.1: flags.append('longer than planned')
    if mw and mw >= 500: flags.append('kick over 500 W')
    status = 'rest ridden' if r['type'] == 'rest' else ('off plan' if 'longer than planned' in flags else 'on plan')
    r.update(actual_h=round(h, 2), np=np_, max_w=mw, tss=round(t), indoor=ind,
             actual=('Indoor ' if ind else '') + f'{hm(h)} at NP {np_} W',
             flags=', '.join(flags), status=status)

# ---- "Today" panel at the top of the page
import html as _h

def fday(s):
    d = D(s); return f'{d:%a} {d.day} {d:%b}'

def today_panel():
    last = fd[-1]
    w = whoop[-1] if whoop else None
    ad = D(asof); mon = ad - dt.timedelta(ad.weekday())
    wk_r = [r for r in week if mon.isoformat() <= r['date'] <= asof and (r.get('actual_h') or 0) > 0]
    wk_tss = sum(fdm[(mon + dt.timedelta(i)).isoformat()]['load'] for i in range((ad - mon).days + 1)
                 if (mon + dt.timedelta(i)).isoformat() in fdm)
    wk_h = sum(r['actual_h'] for r in wk_r)
    lr = rides[-1] if rides else None
    nxt = next((r for r in week if r['status'] == 'upcoming' and r['date'] >= asof), None)
    cards = []
    if w:
        rc = w['recovery']; cls = 'ok' if rc >= 66 else ('warn' if rc >= 50 else 'bad')
        cards.append(('WHOOP recovery', f'<span class="{cls}">{rc}%</span>',
                      f'{fday(w["date"])} · HRV {w["hrv"]} · RHR {w["rhr"]}'))
        cards.append(('Sleep', f'{w["asleep_h"]:.1f} h', f'bed {w["bedtime"]} · {w["sleep_perf"]}% performance'))
    tsb = last['tsb']; tcls = 'ok' if tsb >= -10 else ('warn' if tsb >= -25 else 'bad')
    cards.append(('Form (TSB)', f'<span class="{tcls}">{tsb:+.0f}</span>', f'fitness {last["ctl"]:.0f} · fatigue {last["atl"]:.0f}'))
    cards.append(('This week', f'{wk_tss:.0f} TSS', f'{wk_h:.1f} h · {len(wk_r)} ride{"s" if len(wk_r) != 1 else ""} since {fday(mon.isoformat())}'))
    g = ''.join(f'<div class="t-c"><div class="l">{l}</div><div class="v">{v}</div><div class="s">{_h.escape(s)}</div></div>' for l, v, s in cards)
    parts = [f'<div class="t-h"><b>Today</b><span>updated {fday(asof)}</span></div>', f'<div class="t-g">{g}</div>']
    if lr:
        t_ = tss(lr)
        parts.append(f'<div class="t-n"><b>Last ride · {fday(lr["date"])}</b>{hm(lr["moving_h"])} · NP {lr.get("np") or lr["avg_w"]} W · {t_:.0f} TSS</div>')
    return '<div class="today">' + ''.join(parts) + '</div>'

def week_panel():
    """Mon–Sun plan for the week that holds the next planned day."""
    try:
        notes = load('week_notes.json')
    except FileNotFoundError:
        notes = {}
    nxt = next((r for r in week if r['status'] == 'upcoming' and r['date'] >= asof), None)
    ref = D(nxt['date']) if nxt else D(asof)
    mon = ref - dt.timedelta(ref.weekday())
    days = [(mon + dt.timedelta(i)).isoformat() for i in range(7)]
    byd = {r['date']: r for r in week}
    if not any(d in byd for d in days):
        return ''
    rows = []
    for d in days:
        r = byd.get(d)
        if not r:
            rows.append(f'<details class="wd"><summary><span class="dd">{D(d):%a} {D(d).day}</span><span class="dt">No plan yet</span></summary></details>')
            continue
        st = r['status']
        title = r.get('short') or r['plan'].split(' (')[0].split('. ')[0]
        if st == 'upcoming':
            chip = '<span class="wc next">today</span>' if d == asof else ('<span class="wc next">next</span>' if nxt and d == nxt['date'] else '')
            if r['type'] == 'rest': chip = '<span class="wc rest">rest</span>'
            elif not chip and any(k in title.lower() for k in ('sweet spot', 'threshold', 'vo2', 'ftp test', 'ftp retest')):
                chip = '<span class="wc key">key session</span>'
        else:
            cls = {'on plan': 'ok', 'off plan': 'warn', 'rest ridden': 'bad', 'skipped': 'warn'}.get(st, 'ok')
            chip = f'<span class="wc {cls}">{_h.escape(st)}</span>'
        done = f'<div class="wa">Ridden: {_h.escape(r["actual"])}{" · " + str(r["tss"]) + " TSS" if r.get("tss") else ""}{" · " + _h.escape(r["flags"]) if r.get("flags") else ""}</div>' if st != 'upcoming' else ''
        cur = ' cur' if nxt and d == nxt['date'] else ''
        dl = f'{D(d):%a} {D(d).day}'
        rows.append(f'<details class="wd{cur}"><summary><span class="dd">{dl}</span><span class="dt">{_h.escape(title)}</span>{chip}</summary>'
                    f'<div class="wp">{_h.escape(r["plan"])}</div>{done}</details>')
    note = notes.get(days[0], '')
    head = f'<div class="t-h"><b>This week’s plan</b><span>{D(days[0]).day} {D(days[0]):%b} – {D(days[6]).day} {D(days[6]):%b}</span></div>'
    return ('<div class="today wk">' + head + (f'<div class="wn">{_h.escape(note)}</div>' if note else '') +
            ''.join(rows) + '</div>')

data = dict(static)
try:
    ss_extra = load('sweet_spot_extra.json')
except FileNotFoundError:
    ss_extra = []
have = {r['key'] for r in data.get('sweet_spot', [])}
data['sweet_spot'] = data.get('sweet_spot', []) + [r for r in ss_extra if r['key'] not in have]
data.update(fitness_daily=fd, whoop=whoop, week=week)

ad = D(asof)
asof_s = f'{ad.day} {ad:%b}'
asof_l = f'{ad.day} {ad:%B %Y}'
html = (ROOT / 'template.html').read_text(encoding='utf-8')
html = html.replace('__DATA__', json.dumps(data, ensure_ascii=False).replace('</', '<\\/'))
html = html.replace('__TODAY__', today_panel() + week_panel())
html = html.replace('__ASOF_LONG__', asof_l).replace('__ASOF__', asof_s)
(ROOT / 'index.html').write_text(html, encoding='utf-8')
last = fd[-1]
print(f'built index.html as of {asof}: CTL {last["ctl"]}, ATL {last["atl"]}, TSB {last["tsb"]}')

# ---- exports for the Claude dashboard (same rows as this page)
out = ROOT / 'out'; out.mkdir(exist_ok=True)
for name in ('fitness_daily', 'whoop', 'week', 'sweet_spot'):
    (out / f'{name}.json').write_text(json.dumps(data[name], ensure_ascii=False), encoding='utf-8')
(out / 'asof.txt').write_text(asof, encoding='utf-8')
