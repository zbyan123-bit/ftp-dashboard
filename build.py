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

data = dict(static)
data.update(fitness_daily=fd, whoop=whoop, week=week)

ad = D(asof)
asof_s = f'{ad.day} {ad:%b}'
asof_l = f'{ad.day} {ad:%B %Y}'
html = (ROOT / 'template.html').read_text(encoding='utf-8')
html = html.replace('__DATA__', json.dumps(data, ensure_ascii=False).replace('</', '<\\/'))
html = html.replace('__ASOF_LONG__', asof_l).replace('__ASOF__', asof_s)
(ROOT / 'index.html').write_text(html, encoding='utf-8')
last = fd[-1]
print(f'built index.html as of {asof}: CTL {last["ctl"]}, ATL {last["atl"]}, TSB {last["tsb"]}')
