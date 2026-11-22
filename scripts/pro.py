"""Pro metrics section: live power curve, eFTP (critical power), W', Pmax, TTE,
weekly intensity by power zone, per-ride IF/VI/kJ/carbs/decoupling, HRV normal range,
power profile and personal-best alerts. Pure Python; charts are inline SVG."""
import datetime as dt
import html as H
import math

D = dt.date.fromisoformat
CP_DURS = [180, 300, 480, 600, 720, 900, 1200]
LABEL = {1: '1 s', 5: '5 s', 10: '10 s', 15: '15 s', 30: '30 s', 60: '1 min', 120: '2 min', 180: '3 min',
         300: '5 min', 480: '8 min', 600: '10 min', 720: '12 min', 900: '15 min', 1200: '20 min',
         1800: '30 min', 2400: '40 min', 3600: '60 min', 5400: '90 min'}


def esc(s):
    return H.escape(str(s))


def fday(s):
    d = D(s)
    return f'{d:%a} {d.day} {d:%b}'


def best_curve(rides, since=None, until=None, exclude=None):
    best = {}
    for rid, r in rides.items():
        if 'mmp' not in r or rid == exclude:
            continue
        if since and r['date'] < since:
            continue
        if until and r['date'] > until:
            continue
        for k, v in r['mmp'].items():
            k = int(k)
            if v > best.get(k, (0,))[0]:
                best[k] = (v, r['date'])
    return best


def cp_fit(best):
    pts = [(d, best[d][0]) for d in CP_DURS if d in best]
    if len(pts) < 3:
        return None, None
    xs = [d for d, _ in pts]
    ys = [d * p for d, p in pts]  # work (J) = CP * t + W'
    n = len(xs); mx = sum(xs) / n; my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    cp = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    wp = my - cp * mx
    return cp, wp


def tte(best, eftp):
    ds = sorted(best)
    held = [d for d in ds if best[d][0] >= eftp]
    if not held:
        return None
    last = max(held)
    nxt = [d for d in ds if d > last]
    if not nxt:
        return last
    d2 = nxt[0]; p1 = best[last][0]; p2 = best[d2][0]
    if p1 == p2:
        return last
    f = (p1 - eftp) / (p1 - p2)  # interpolate on log time
    return round(math.exp(math.log(last) + f * (math.log(d2) - math.log(last))))


# ---------- SVG helpers ----------
def svg_open(w, h):
    return f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" preserveAspectRatio="xMidYMid meet" class="psvg">'


def curve_svg(series, ftp, goal):
    W, Hh, l, r, t, b = 640, 300, 44, 12, 12, 34
    ds = [1, 5, 15, 60, 300, 1200, 3600]
    allv = [p for s in series for _, p in s['pts']] + [ftp, goal]
    ymax = max(allv) * 1.05
    ymin = 100
    lx = lambda d: l + (math.log(d) - math.log(1)) / (math.log(5400) - math.log(1)) * (W - l - r)
    sy = lambda p: t + (1 - (math.log(p) - math.log(ymin)) / (math.log(ymax) - math.log(ymin))) * (Hh - t - b)
    o = [svg_open(W, Hh)]
    for p in [150, 200, 250, 300, 400, 600, 800, 1000]:
        if ymin <= p <= ymax:
            o.append(f'<line x1="{l}" x2="{W-r}" y1="{sy(p):.1f}" y2="{sy(p):.1f}" class="g"/><text x="{l-6}" y="{sy(p)+4:.1f}" text-anchor="end" class="ax">{p}</text>')
    for d in ds:
        o.append(f'<text x="{lx(d):.1f}" y="{Hh-12}" text-anchor="middle" class="ax">{LABEL.get(d, d)}</text>')
    for val, cls, lab in ((ftp, 'ref', f'FTP {ftp} W'), (goal, 'goal', f'Goal {goal} W')):
        o.append(f'<line x1="{l}" x2="{W-r}" y1="{sy(val):.1f}" y2="{sy(val):.1f}" class="{cls}"/><text x="{l+6}" y="{sy(val)+(-5 if cls == "goal" else 14):.1f}" class="ax">{lab}</text>')
    for s in series:
        pts = sorted(s['pts'])
        if len(pts) < 2:
            continue
        d = 'M' + ' L'.join(f'{lx(x):.1f},{sy(p):.1f}' for x, p in pts)
        o.append(f'<path d="{d}" class="{s["cls"]}"/>')
        for x, p in pts:
            o.append(f'<circle cx="{lx(x):.1f}" cy="{sy(p):.1f}" r="3" class="{s["cls"]}d"><title>{LABEL.get(x, x)}: {p:.0f} W</title></circle>')
    o.append('</svg>')
    return ''.join(o)


def intensity_svg(weeks):
    W, rowh, l = 640, 30, 74
    Hh = rowh * len(weeks) + 10
    o = [svg_open(W, Hh)]
    for i, wk in enumerate(weeks):
        y = 5 + i * rowh
        tot = sum(wk['z3']) or 1
        x = l
        o.append(f'<text x="{l-8}" y="{y+17}" text-anchor="end" class="ax">{esc(wk["label"])}</text>')
        for j, cls in enumerate(('ze', 'zg', 'zh')):
            wdt = wk['z3'][j] / tot * (W - l - 70)
            if wdt > 0:
                o.append(f'<rect x="{x:.1f}" y="{y}" width="{wdt:.1f}" height="{rowh-8}" class="{cls}"><title>{["Easy","Middle (tempo to threshold)","Hard"][j]}: {wk["z3"][j]/tot*100:.0f}%</title></rect>')
                if wdt > 34:
                    o.append(f'<text x="{x+wdt/2:.1f}" y="{y+16}" text-anchor="middle" class="zl">{wk["z3"][j]/tot*100:.0f}%</text>')
            x += wdt
        o.append(f'<text x="{W-4}" y="{y+16}" text-anchor="end" class="ax">{wk["hours"]:.1f} h{" ⚠" if wk["grey"] else ""}</text>')
    o.append('</svg>')
    return ''.join(o)


def hrv_svg(pts):
    W, Hh, l, r, t, b = 640, 220, 40, 10, 10, 28
    vals = [v for p in pts for v in (p['hrv'], p.get('lo'), p.get('hi'), p.get('avg7')) if v]
    lo, hi = min(vals) * 0.95, max(vals) * 1.05
    n = len(pts)
    sx = lambda i: l + i / max(1, n - 1) * (W - l - r)
    sy = lambda v: t + (1 - (v - lo) / (hi - lo)) * (Hh - t - b)
    o = [svg_open(W, Hh)]
    for v in range(int(lo // 10 * 10 + 10), int(hi) + 1, 10):
        o.append(f'<line x1="{l}" x2="{W-r}" y1="{sy(v):.1f}" y2="{sy(v):.1f}" class="g"/><text x="{l-6}" y="{sy(v)+4:.1f}" text-anchor="end" class="ax">{v}</text>')
    band = [(i, p) for i, p in enumerate(pts) if p.get('lo')]
    if len(band) > 1:
        top = ' L'.join(f'{sx(i):.1f},{sy(p["hi"]):.1f}' for i, p in band)
        bot = ' L'.join(f'{sx(i):.1f},{sy(p["lo"]):.1f}' for i, p in reversed(band))
        o.append(f'<path d="M{top} L{bot} Z" class="band"/>')
    for i, p in enumerate(pts):
        o.append(f'<circle cx="{sx(i):.1f}" cy="{sy(p["hrv"]):.1f}" r="2.5" class="dot"><title>{fday(p["date"])}: {p["hrv"]} ms</title></circle>')
    av = [(i, p) for i, p in enumerate(pts) if p.get('avg7')]
    if len(av) > 1:
        o.append('<path d="M' + ' L'.join(f'{sx(i):.1f},{sy(p["avg7"]):.1f}' for i, p in av) + '" class="l1"/>')
    for i in (0, n // 2, n - 1):
        o.append(f'<text x="{sx(i):.1f}" y="{Hh-8}" text-anchor="middle" class="ax">{fday(pts[i]["date"])[4:]}</text>')
    o.append('</svg>')
    return ''.join(o)


def profile_svg(items, goal_wkg):
    W, rowh, l = 640, 40, 70
    Hh = rowh * len(items) + 6
    mx = max(max(i['wkg'] for i in items), 1) * 1.12
    o = [svg_open(W, Hh)]
    for k, it in enumerate(items):
        y = 4 + k * rowh
        wdt = it['wkg'] / mx * (W - l - 150)
        o.append(f'<text x="{l-8}" y="{y+20}" text-anchor="end" class="ax">{esc(it["label"])}</text>')
        o.append(f'<rect x="{l}" y="{y+6}" width="{wdt:.1f}" height="{rowh-16}" class="pb"/>')
        o.append(f'<text x="{l+wdt+6:.1f}" y="{y+20}" class="pv">{it["wkg"]:.2f} W/kg · {it["w"]:.0f} W{(" · " + esc(it["note"])) if it.get("note") else ""}</text>')
    o.append('</svg>')
    return ''.join(o)


# ---------- main entry ----------
def build(rides_m, whoop, static_curve, ftp, kg, asof, week_rows):
    rides = {k: v for k, v in rides_m.items() if 'mmp' in v}
    if not rides:
        return '', ''
    goal = round(4.3 * kg)
    s90 = (D(asof) - dt.timedelta(days=90)).isoformat()
    best90 = best_curve(rides, since=s90)
    cp, wp = cp_fit(best90)
    e20 = round(best90[1200][0] * 0.95) if 1200 in best90 else None
    eftp = round(cp) if cp else e20
    pmax = best90.get(1, (None,))[0]
    tte_s = tte(best90, eftp) if eftp else None
    # all-time reference: Strava bests table (to 14 Nov) + every analysed ride
    stat = {int(r['seconds']): float(r['watts']) for r in static_curve if r.get('seconds')}
    def stat_at(d):
        near = [s for s in stat if abs(s - d) / d <= 0.05]
        return stat[near[0]] if near else 0

    # ---- PR alerts (last 7 days)
    recent_from = (D(asof) - dt.timedelta(days=6)).isoformat()
    prs = []
    for rid, r in rides.items():
        if r['date'] < recent_from:
            continue
        prev = best_curve(rides, exclude=rid)
        for d in (5, 60, 300, 600, 1200, 3600):
            v = r['mmp'].get(str(d))
            if v and v > max(prev.get(d, (0,))[0], stat_at(d)) and prev.get(d):
                prs.append((r['date'], d, v))
    prs.sort(reverse=True)

    # ---- weekly intensity by power zone (last 8 weeks, Mon-Sun)
    ad = D(asof); mon = ad - dt.timedelta(days=ad.weekday())
    weeks = []
    for k in range(7, -1, -1):
        a = mon - dt.timedelta(days=7 * k); b = a + dt.timedelta(days=6)
        z = [0] * 7; secs = 0
        for r in rides.values():
            if a.isoformat() <= r['date'] <= b.isoformat():
                z = [x + y for x, y in zip(z, r['zones'])]; secs += r['moving_s']
        if secs == 0:
            continue
        z3 = [z[0] + z[1], z[2] + z[3], sum(z[4:])]
        grey = z[2] / max(1, sum(z)) > 0.20
        weeks.append(dict(label=f'{a.day} {a:%b}', z3=z3, hours=secs / 3600, grey=grey, tempo=z[2] / max(1, sum(z))))

    # ---- per-ride table (latest 12)
    latest = sorted(rides.values(), key=lambda r: r['date'], reverse=True)[:12]
    rows = ''.join(
        f'<tr><td>{fday(r["date"])[:-4]}</td><td class="wrap">{esc(r["name"])}{" (indoor)" if r.get("indoor") else ""}</td>'
        f'<td class="n">{r["moving_s"]/3600:.1f}</td><td class="n">{r["np"]}</td><td class="n">{r["IF"]:.2f}</td>'
        f'<td class="n">{(r["VI"] or 0):.2f}</td><td class="n">{r["kj"]}</td><td class="n">{r["carbs_g"]}</td>'
        f'<td class="n">{round(r["carbs_g"]/max(0.25, r["moving_s"]/3600))}</td>'
        f'<td class="n">{"" if r.get("decoupling") is None else str(r["decoupling"]) + "%"}</td></tr>' for r in latest)

    # ---- decoupling: latest long steady ride
    dec = [r for r in sorted(rides.values(), key=lambda r: r['date']) if r.get('decoupling') is not None]
    lastdec = dec[-1] if dec else None

    # ---- HRV normal range (ln rMSSD: 60-day mean ± 0.5 SD; 7-day rolling average)
    wh = [w for w in sorted(whoop, key=lambda w: w['date']) if w.get('hrv')]
    pts = []
    for i, w in enumerate(wh):
        p = {'date': w['date'], 'hrv': w['hrv']}
        last7 = [math.log(x['hrv']) for x in wh[max(0, i - 6):i + 1]]
        if len(last7) >= 4:
            p['avg7'] = round(math.exp(sum(last7) / len(last7)), 1)
        base = [math.log(x['hrv']) for x in wh[max(0, i - 60):i]]
        if len(base) >= 14:
            m = sum(base) / len(base); sd = (sum((x - m) ** 2 for x in base) / (len(base) - 1)) ** 0.5
            p['lo'] = round(math.exp(m - 0.5 * sd), 1); p['hi'] = round(math.exp(m + 0.5 * sd), 1)
        pts.append(p)
    pts = pts[-45:]
    hrv_state = None
    if pts and pts[-1].get('lo') and pts[-1].get('avg7'):
        a7, lo, hi = pts[-1]['avg7'], pts[-1]['lo'], pts[-1]['hi']
        hrv_state = ('below your normal range' if a7 < lo else ('above your normal range' if a7 > hi else 'inside your normal range'), a7, lo, hi)

    # ---- power profile (W/kg)
    def bestw(d):
        return max(best_curve(rides).get(d, (0,))[0], stat_at(d))
    ftp_wkg = ftp / kg
    rating = 'Superior' if ftp_wkg >= 5.05 else 'Excellent' if ftp_wkg >= 3.93 else 'Good' if ftp_wkg >= 2.79 else 'Fair' if ftp_wkg >= 2.23 else 'Untrained'
    prof = [dict(label='5 s', w=bestw(5), wkg=bestw(5) / kg), dict(label='1 min', w=bestw(60), wkg=bestw(60) / kg),
            dict(label='5 min', w=bestw(300), wkg=bestw(300) / kg),
            dict(label='FTP', w=ftp, wkg=ftp_wkg, note=f'{rating} (Garmin scale)' + (f' · Excellent from {round(3.93*kg)} W' if ftp_wkg < 3.93 else '') + ' · goal 4.3')]
    prof = [p for p in prof if p['w']]

    # ---- assemble
    def tile(lab, val, unit='', sub='', cls=''):
        return (f'<div class="tile {cls}"><span class="lab">{lab}</span><span class="val"><span class="num">{val}</span>'
                f'<span class="unit">{unit}</span></span>{f"<span class=unit>{esc(sub)}</span>" if sub else ""}</div>')
    tiles = [tile('Estimated FTP (eFTP)', eftp or '–', 'W', f'{eftp/kg:.2f} W/kg · critical-power fit, 90 days' if eftp else ''),
             tile('95% of best 20 min', e20 or '–', 'W', '90 days' if e20 else ''),
             tile('Time at eFTP (TTE)', f'{tte_s//60}' if tte_s else '–', 'min', 'longest held, 90 days'),
             tile("W′ (anaerobic capacity)", f'{wp/1000:.1f}' if wp else '–', 'kJ', 'from the same fit'),
             tile('Pmax (peak power)', f'{pmax:.0f}' if pmax else '–', 'W', '1-second best, 90 days')]
    if lastdec:
        tiles.append(tile('Decoupling, last long steady ride', f'{lastdec["decoupling"]}', '%', f'{fday(lastdec["date"])} · under 5% is good',
                          'good' if lastdec['decoupling'] < 5 else 'warn'))
    if hrv_state:
        tiles.append(tile('HRV, 7-day average', f'{hrv_state[1]:.0f}', 'ms', f'{hrv_state[0]} ({hrv_state[2]:.0f}–{hrv_state[3]:.0f})',
                          'good' if 'inside' in hrv_state[0] or 'above' in hrv_state[0] else 'warn'))
    pr_html = ''
    if prs:
        pr_html = '<div class="card"><h3>New personal bests (last 7 days)</h3><ul class="prl">' + ''.join(
            f'<li><b>{LABEL[d]}: {v:.0f} W</b> ({v/kg:.2f} W/kg) · {fday(dd)}</li>' for dd, d, v in prs[:6]) + '</ul></div>'
    curve = curve_svg([
        {'cls': 'l1', 'pts': [(d, v) for d, (v, _) in best90.items() if d >= 5]},
        {'cls': 'l2', 'pts': [(d, v) for d, v in stat.items() if d >= 5]}], ftp, goal)
    grey_weeks = [w for w in weeks if w['grey']]
    sec = f'''
  <section id="pro" aria-labelledby="pro-h">
    <div class="sec-head"><span class="eyebrow">Pro metrics · updated automatically</span><h2 id="pro-h">eFTP {eftp or "–"} W{f", held for about {tte_s//60} min" if tte_s else ""}</h2></div>
    <div class="tiles">{''.join(tiles)}</div>
    {pr_html}
    <div class="card"><h3>Power curve, last 90 days</h3><p class="note">Best average power for each duration (log scale). Solid: last 90 days from every ride. Dashed: Strava best-efforts table to 14 Nov. eFTP comes from a critical-power fit of the 3–20 min bests, so it rises only after hard efforts in that range.</p>
      <div class="lg"><span class="k k1"></span>Last 90 days <span class="k k2"></span>Strava bests to 14 Nov</div>{curve}</div>
    <div class="card"><h3>Intensity by power zone, each week</h3><p class="note">Share of riding time: easy under 75% of FTP, middle 75–105% (tempo, sweet spot, threshold), hard above 105%. ⚠ marks weeks with more than 20% tempo (75–90%), the grey zone.</p>
      <div class="lg"><span class="k ze"></span>Easy <span class="k zg"></span>Middle <span class="k zh"></span>Hard</div>{intensity_svg(weeks) if weeks else '<p class="note">No rides analysed yet.</p>'}</div>
    <div class="card"><h3>HRV against your normal range</h3><p class="note">Dots: WHOOP HRV each morning. Line: 7-day average. Band: your normal range (60-day average ± half a standard deviation, on log HRV). A 7-day average below the band is an early fatigue sign.</p>
      {hrv_svg(pts) if len(pts) > 3 else '<p class="note">Not enough mornings yet.</p>'}</div>
    <div class="card"><h3>Power profile</h3><p class="note">Best 5 s, 1 min and 5 min power and working FTP, in W/kg at {kg} kg. FTP rating uses Garmin's male scale (Excellent 3.93–5.04, Superior 5.05+).</p>{profile_svg(prof, 4.3)}</div>
    <div class="card"><h3>Ride by ride</h3><p class="note">IF = NP ÷ FTP (1.0 = an all-out hour). VI = NP ÷ average power (steady rides under 1.05). Carbs are an estimate from work done and intensity. Decoupling only on steady rides over 1 hour.</p>
      <div class="tbl"><table class="pt"><thead><tr><th>Date</th><th>Ride</th><th class="n">h</th><th class="n">NP</th><th class="n">IF</th><th class="n">VI</th><th class="n">kJ</th><th class="n">Carbs g</th><th class="n">g/h</th><th class="n">Decoup.</th></tr></thead><tbody>{rows}</tbody></table></div></div>
  </section>
'''
    today = ''
    bits = []
    if eftp:
        bits.append(f'eFTP {eftp} W ({eftp/kg:.2f} W/kg)')
    if hrv_state:
        bits.append(f'HRV {hrv_state[0]}')
    if grey_weeks and weeks and weeks[-1]['grey']:
        bits.append('⚠ grey-zone week')
    if bits:
        today += f'<div class="t-n"><b>Pro metrics</b>{" · ".join(esc(b) for b in bits)}</div>'
    if prs:
        dd, d, v = prs[0]
        today += f'<div class="t-n"><b>New best · {fday(dd)}</b>{LABEL[d]}: {v:.0f} W ({v/kg:.2f} W/kg)</div>'
    return sec, today
