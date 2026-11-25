"""Build index.html from template.html and data/*.json.

Run:  python3 build.py
Daily inputs (appended by the morning check-in): data/rides.json, data/whoop.json, data/week.json.
Everything in data/static.json is a snapshot from 20 Nov 2026 and is not recomputed here.
"""
import json, datetime as dt, pathlib

ROOT = pathlib.Path(__file__).parent
FTP = 255  # working FTP in W. Change here when FTP changes.
KG = 68  # body weight for W/kg. Change when the athlete gives a new weight.
GOAL_WKG = 4.3  # target W/kg
GOAL_BY = 'June 2027'
D = dt.date.fromisoformat
load = lambda f: json.loads((ROOT / 'data' / f).read_text(encoding='utf-8'))

static = load('static.json')
base = load('fitness_base.json')
rides = sorted(load('rides.json'), key=lambda r: r['date'])
try:  # prefer NP from the full 1-second power data (ride_metrics.json) when the sync job has it
    _met = load('ride_metrics.json')
    for _r in rides:
        _m = _met.get(str(_r.get('strava_id')))
        if _m and _m.get('np'):
            _r['np'] = _m['np']
except FileNotFoundError:
    pass
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

# ---- fitness (CTL 42 d, ATL 7 d)
# From the first day with full 1-second ride analysis (data/ride_metrics.json) the daily load is
# recomputed from that data; days before it keep the older series in fitness_base.json.
try:
    _met_all = {k: v for k, v in load('ride_metrics.json').items() if 'mmp' in v}
except FileNotFoundError:
    _met_all = {}
met_load = {}
for _m in _met_all.values():
    met_load[_m['date']] = met_load.get(_m['date'], 0) + _m['moving_s'] / 3600 * (_m['np'] / FTP) ** 2 * 100
met_ids = {int(k) for k in _met_all}
for r in rides:  # rides not analysed yet (new today) fall back to rides.json
    if r.get('strava_id') not in met_ids:
        met_load[r['date']] = met_load.get(r['date'], 0) + tss(r)
day_load = dict(met_load) if met_load else day_load
cut = min(_m['date'] for _m in _met_all.values()) if _met_all else None
base_cut = [dict(r) for r in base if cut is None or r['date'] < cut]
fd = base_cut if base_cut else [dict(r) for r in base]
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
    cards.append(('Form (TSB)', f'<span class="{tcls}">{int(tsb + 0.5) if tsb >= 0 else -int(-tsb + 0.5):+d}</span>', f'fitness {last["ctl"]:.0f} · fatigue {last["atl"]:.0f}'))
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

def hero_panel():
    """Orange header band: FTP now, progress to the W/kg goal, next test."""
    goal_w = round(GOAL_WKG * KG)
    pct = min(100, round(FTP / goal_w * 100))
    test = next((r for r in week if r['date'] >= asof and r['status'] == 'upcoming'
                 and 'ftp' in (r.get('short') or r['plan']).lower() and 'test' in (r.get('short') or r['plan']).lower()), None)
    nt = f'Next FTP test {fday(test["date"])}' if test else ''
    mark = ('<svg class="mark" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 18l5-6 4 3 7-9" fill="none" stroke="currentColor" '
            'stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/><circle cx="19" cy="6" r="2.2" fill="currentColor"/></svg>')
    return (f'<header class="hero"><div class="hero-in">'
            f'<div class="hero-top"><div class="brand">{mark}<span>FTP Dashboard</span></div><div class="upd">Strava + WHOOP · updated {fday(asof)}</div></div>'
            f'<div class="hero-main"><div class="hm-ftp"><div class="k">Working FTP</div>'
            f'<div class="big">{FTP}<small>W</small></div><div class="sub">{FTP / KG:.2f} W/kg at {KG} kg</div></div>'
            f'<div class="hm-goal"><div class="row"><b>Road to {GOAL_WKG} W/kg</b><span>{goal_w} W by {GOAL_BY}</span></div>'
            f'<div class="bar" role="img" aria-label="{pct}% of goal power"><i style="width:{pct}%"></i></div>'
            f'<div class="row sm"><span>{pct}% of goal power · {goal_w - FTP} W to go</span><span>{nt}</span></div></div></div>'
            f'</div></header>')

data = dict(static)
try:
    ss_extra = load('sweet_spot_extra.json')
except FileNotFoundError:
    ss_extra = []
have = {r['key'] for r in data.get('sweet_spot', [])}
data['sweet_spot'] = data.get('sweet_spot', []) + [r for r in ss_extra if r['key'] not in have]
data.update(fitness_daily=fd, whoop=whoop, week=week)

# ---- Load section: weekly hours/fitness, ramp and stress, and the "today" tiles, kept current
day_hours = {}
for _m in _met_all.values():
    day_hours[_m['date']] = day_hours.get(_m['date'], 0) + _m['moving_s'] / 3600
for r in rides:
    if r.get('strava_id') not in met_ids:
        day_hours[r['date']] = day_hours.get(r['date'], 0) + r['moving_h']

def _weeks():
    """(monday, sunday) pairs covering the fitness series, last one may be partial."""
    d0 = D(fd[0]['date']); m = d0 - dt.timedelta(d0.weekday())
    if m < d0: m += dt.timedelta(7)
    out = []
    while m <= D(asof):
        out.append((m, m + dt.timedelta(6))); m += dt.timedelta(7)
    return out

def live_weekly(old):
    keep = {w['week_end']: w for w in old}
    new = []; prev_ctl = None
    for w in old:
        if w['week_end'] < _weeks()[0][1].isoformat():
            new.append(w); prev_ctl = w['fitness_ctl']
    for mon, sun in _weeks():
        days = [(mon + dt.timedelta(i)).isoformat() for i in range(7) if (mon + dt.timedelta(i)).isoformat() <= asof]
        endr = fdm[days[-1]]
        ld = sum(fdm[d]['load'] for d in days if d in fdm)
        if cut and mon.isoformat() < cut and sun.isoformat() in keep:
            hrs = keep[sun.isoformat()]['hours']
        else:
            hrs = round(sum(day_hours.get(d, 0) for d in days), 1)
        chg = None if prev_ctl is None else round(endr['ctl'] - prev_ctl, 1)
        flag = 'ramp' if chg is not None and chg > 7 else ('low' if hrs < 5 and '06' <= sun.isoformat()[5:7] <= '09' else '')
        new.append(dict(week_end=sun.isoformat(), hours=hrs, load=round(ld), fitness_ctl=endr['ctl'], fatigue_atl=endr['atl'],
                        ctl_change=chg, flag=flag, partial=len(days) < 7))
        prev_ctl = endr['ctl']
    return new

def live_load_weekly(old):
    first = _weeks()[0][0].isoformat()
    new = [w for w in old if w['week_start'] < first]
    prev = None
    for w in new: prev = w['ctl_end']
    for mon, sun in _weeks():
        days = [(mon + dt.timedelta(i)).isoformat() for i in range(7) if (mon + dt.timedelta(i)).isoformat() <= asof]
        loads = [fdm[d]['load'] for d in days if d in fdm]
        endr = fdm[days[-1]]
        tot = sum(loads); mean = tot / len(loads)
        sd = (sum((x - mean) ** 2 for x in loads) / len(loads)) ** 0.5
        mono = round(mean / sd, 2) if sd > 0 else None
        ramp = None if prev is None else round(endr['ctl'] - prev, 1)
        part = len(days) < 7
        new.append(dict(week_start=mon.isoformat(), week_end=days[-1], days=len(days), tss=round(tot), ctl_end=endr['ctl'],
                        atl_end=endr['atl'], tsb_end=endr['tsb'], ramp=ramp if ramp is not None else 0.0, monotony=mono,
                        strain=round(tot * mono) if mono else None,
                        flag='partial week' if part else ('ramp over 7' if ramp and ramp > 7 else ''), partial=part))
        prev = endr['ctl']
    return new

def live_kpis(old):
    lastd = fd[-1]; ad_ = D(asof)
    l7 = round(sum(day_hours.get((ad_ - dt.timedelta(i)).isoformat(), 0) for i in range(7)), 1)
    pk = max(fd, key=lambda r: r['ctl'])
    pk_old = max((w for w in static.get('weekly', []) if w['week_end'] < fd[0]['date']), key=lambda w: w['fitness_ctl'], default=None)
    if pk_old and pk_old['fitness_ctl'] > pk['ctl']:
        pk_v, pk_d = pk_old['fitness_ctl'], pk_old['week_end']
    else:
        pk_v, pk_d = pk['ctl'], pk['date']
    upd = {'ctl': (lastd['ctl'], 'Fitness (CTL)'), 'atl': (lastd['atl'], 'Fatigue (ATL)'), 'tsb': (lastd['tsb'], 'Form (TSB)'),
           'last7': (l7, f'Last 7 days to {fday(asof)}, all rides'), 'peak_ctl': (pk_v, f'Peak fitness ({fday(pk_d)})')}
    out = []
    for k in old:
        k = dict(k)
        if k.get('metric') in upd:
            k['value'], k['label'] = upd[k['metric']]
        out.append(k)
    return out

data['weekly'] = live_weekly(static.get('weekly', []))
data['load_weekly'] = live_load_weekly(static.get('load_weekly', []))
data['kpis'] = live_kpis(static.get('kpis', []))

def live_elite(old, lw):
    full = [w for w in lw if not w['partial']]
    cur = lw[-1] if lw and lw[-1]['partial'] else None
    lf = full[-1] if full else None
    def sgn(v): return ('+' if v >= 0 else '−') + f'{abs(v):.1f}'
    def lab(a, b):
        a, b = D(a), D(b)
        return f'{a.day}–{b.day} {b:%b}' if a.month == b.month else f'{a.day} {a:%b} – {b.day} {b:%b}'
    upd = {'ctl_now': round(fd[-1]['ctl']), 'tsb_now': ('+' if fd[-1]['tsb'] >= 0 else '−') + str(round(abs(fd[-1]['tsb'])))}
    if lf:
        upd.update(ramp_last=sgn(lf['ramp']), ramp_last_lab=f'Week of {D(lf["week_start"]).day} {D(lf["week_start"]):%b}',
                   tss_last=lf['tss'], mono_last=f'{lf["monotony"]:.2f}' if lf['monotony'] else '–')
    upd['tss_cur'] = cur['tss'] if cur else 0
    upd['cur_lab'] = lab(cur['week_start'], cur['week_end']) if cur else 'new week'
    out = [dict(k, value=upd[k['metric']]) if k.get('metric') in upd else dict(k) for k in old]
    have = {k['metric'] for k in out}
    out += [dict(metric=m, value=v) for m, v in upd.items() if m not in have]
    return out

data['elite_kpis'] = live_elite(static.get('elite_kpis', []), data['load_weekly'])

ad = D(asof)
asof_s = f'{ad.day} {ad:%b}'
asof_l = f'{ad.day} {ad:%B %Y}'
html = (ROOT / 'template.html').read_text(encoding='utf-8')
html = html.replace('__DATA__', json.dumps(data, ensure_ascii=False).replace('</', '<\\/'))
import sys as _sys
_sys.path.insert(0, str(ROOT / 'scripts'))
import pro as _pro
try:
    _rm = load('ride_metrics.json')
except FileNotFoundError:
    _rm = {}
# ---- Power zones section (follows FTP automatically)
HR_MAX = 202  # estimated maximum heart rate (not measured)
HR_ZONES = [(0, 120), (121, 140), (141, 160), (161, 180), (181, None), (None, None), (None, None)]
ZONES = [  # name, lower %, upper %, what it is for
    ('Z1', 'Recovery', 0, 55, 'Spinning. Active recovery, warm-up and cool-down.'),
    ('Z2', 'Endurance', 56, 75, 'Base miles. You can talk. Most of your hours should be here.'),
    ('Z3', 'Tempo', 76, 90, 'Comfortably hard. Useful in small doses; too much is the grey zone.'),
    ('Z4', 'Threshold', 91, 105, 'Around FTP. Sweet spot (88–94%) sits at its lower edge. Intervals of 10–20 min.'),
    ('Z5', 'VO2max', 106, 120, 'Hard 3–8 min efforts. Raises your ceiling.'),
    ('Z6', 'Anaerobic', 121, 150, 'Short 30 s–2 min efforts.'),
    ('Z7', 'Sprint', 151, None, 'Under 30 s, all-out.'),
]
ZCOL = ['#7fb8a4', '#3fa37a', '#e0a020', '#ef6420', '#d9483b', '#a3304f', '#6b2a6b']

def _w(pct):
    return int(FTP * pct / 100 + 0.5)

def zones_section():
    scale = 400
    rows = []
    for i, (z, name, lo, hi, use) in enumerate(ZONES):
        wlo = 0 if lo == 0 else _w(lo)
        whi = None if hi is None else _w(hi)
        watts = f'under {whi + 1} W' if lo == 0 else (f'{wlo}+ W' if whi is None else f'{wlo}–{whi} W')
        pct = f'under 56%' if lo == 0 else (f'{lo}%+' if hi is None else f'{lo}–{hi}%')
        a, b = wlo, (scale if whi is None else min(whi, scale))
        bar = (f'<div class="zt"><i style="left:{a / scale * 100:.1f}%;width:{max(b - a, 6) / scale * 100:.1f}%;background:{ZCOL[i]}"></i></div>')
        h_lo, h_hi = HR_ZONES[i]
        hr = '' if h_lo is None and h_hi is None else (f'under {h_hi + 1}' if h_lo == 0 else (f'{h_lo}+' if h_hi is None else f'{h_lo}–{h_hi}'))
        rows.append(f'<tr><td><span class="zdot" style="background:{ZCOL[i]}"></span><b>{z}</b> {name}</td><td class="n"><b>{watts}</b></td>'
                    f'<td class="n zp">{pct}</td><td class="zbar">{bar}</td><td class="n zh">{hr}</td><td class="wrap zu">{_h.escape(use)}</td></tr>')
    ssl, ssh = _w(88), _w(94)
    table = ('<div class="tbl"><table class="zt-t"><thead><tr><th>Zone</th><th class="n">Power</th><th class="n zp">% FTP</th><th class="zbar"></th>'
             '<th class="n zh">Heart rate</th><th class="zu">Use</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>')
    # time in zones, last 28 days
    cutoff = (D(asof) - dt.timedelta(28)).isoformat()
    tot = [0] * 7
    n_r = 0
    for v in _rm.values():
        if 'zones' in v and v.get('date', '') > cutoff and len(v['zones']) == 7:
            n_r += 1
            for i in range(7): tot[i] += v['zones'][i]
    tsum = sum(tot)
    if tsum:
        pc = [t / tsum * 100 for t in tot]
        segs = ''.join(f'<i style="width:{p:.2f}%;background:{ZCOL[i]}" title="Z{i + 1} {p:.0f}%"></i>' for i, p in enumerate(pc) if p > 0.2)
        leg = ''.join(f'<span><i style="background:{ZCOL[i]}"></i>Z{i + 1} <b>{pc[i]:.0f}%</b> · {tot[i] / 3600:.1f} h</span>' for i in range(7))
        easy, tempo, hard = pc[0] + pc[1], pc[2], sum(pc[3:])
        flag = ('Tempo is above 20%: that is the grey zone, hard enough to tire you but not hard enough to push FTP.' if tempo > 20
                else 'Tempo share is under 20%, so the grey zone is not a problem.')
        tz = (f'<div class="card"><h3>Time in each zone, last 28 days</h3>'
              f'<p class="note">{n_r} rides, indoor and outdoor, from 1-second power at FTP {FTP} W.</p>'
              f'<div class="zstack">{segs}</div><div class="zleg">{leg}</div>'
              f'<p class="zsum"><b>{easy:.0f}%</b> easy (Z1–Z2) · <b>{tempo:.0f}%</b> tempo (Z3) · <b>{hard:.0f}%</b> hard (Z4+). {flag}</p></div>')
    else:
        tz = ''
    zs = ('<section id="zones" aria-labelledby="zn-h"><div class="sec-head"><span class="eyebrow">Power zones</span>'
          f'<h2 id="zn-h">Your zones at FTP {FTP} W ({FTP / KG:.2f} W/kg)</h2></div>'
          f'<div class="card">{table}<p class="note">Based on % of FTP (Coggan). Sweet spot is {ssl}–{ssh} W (88–94%). '
          f'Heart rate zones use an estimated maximum of about {HR_MAX} bpm, not a tested one. The zones change by themselves when FTP is updated.</p></div></section>')
    zt = (f'<section id="zonetime" aria-labelledby="zq-h"><div class="sec-head"><span class="eyebrow">Time in zones</span>'
          f'<h2 id="zq-h">Where your last 28 days of riding went</h2></div>{tz}</section>') if tz else ''
    return zs + zt

pro_sec, pro_today = _pro.build(_rm, whoop, static.get('power_curve', []), FTP, KG, asof, week)
_tp = today_panel()
if pro_today:
    _tp = _tp[:-len('</div>')] + pro_today + '</div>'
html = html.replace('__PRO__', pro_sec + zones_section())
html = html.replace('__TODAY__', hero_panel() + '<div class="top">' + _tp + week_panel() + '</div>')
html = html.replace('__ASOF_LONG__', asof_l).replace('__ASOF__', asof_s)
(ROOT / 'index.html').write_text(html, encoding='utf-8')
last = fd[-1]
print(f'built index.html as of {asof}: CTL {last["ctl"]}, ATL {last["atl"]}, TSB {last["tsb"]}')

# ---- exports for the Claude dashboard (same rows as this page)
out = ROOT / 'out'; out.mkdir(exist_ok=True)
for name in ('fitness_daily', 'whoop', 'week', 'sweet_spot'):
    (out / f'{name}.json').write_text(json.dumps(data[name], ensure_ascii=False), encoding='utf-8')
(out / 'asof.txt').write_text(asof, encoding='utf-8')
