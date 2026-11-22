"""Pull new Strava rides and WHOOP mornings, then rebuild the dashboard.

Runs on GitHub Actions (see .github/workflows/sync.yml). Tokens live in state/tokens.enc,
encrypted with the TOKEN_KEY secret, because WHOOP (and sometimes Strava) issue a new
refresh token on every refresh and the new one must be kept for next time.

Never print tokens or secrets: this repository and its Action logs are public.
"""
import datetime as dt
import json
import os
import pathlib
import sys
import time
import urllib.parse
import urllib.request

from cryptography.fernet import Fernet

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / 'data'
STATE = ROOT / 'state' / 'tokens.enc'
LOCAL_TZ = dt.timezone(dt.timedelta(hours=8))  # Asia/Kuala_Lumpur


# ---------- token store ----------
def fernet():
    key = os.environ.get('TOKEN_KEY', '').strip()
    if not key:
        sys.exit('TOKEN_KEY secret is missing')
    return Fernet(key.encode())


def load_tokens():
    if not STATE.exists():
        return {}
    return json.loads(fernet().decrypt(STATE.read_bytes()))


def save_tokens(tok):
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_bytes(fernet().encrypt(json.dumps(tok).encode()))


# ---------- http ----------
def http(method, url, data=None, headers=None):
    body = None
    h = {'User-Agent': 'ftp-dashboard/1.0 (personal training dashboard)', 'Accept': 'application/json'}
    h.update(headers or {})
    if data is not None:
        body = urllib.parse.urlencode(data).encode()
        h['Content-Type'] = 'application/x-www-form-urlencoded'
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read() or b'null')
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            raw = e.read() or b''
            try:
                detail = json.loads(raw or b'{}')
                detail = {k: detail[k] for k in ('message', 'error', 'error_description', 'errors') if k in detail}
            except Exception:
                detail = {'body': raw[:120].decode('utf-8', 'replace')}
            raise RuntimeError(f'{method} {url.split("?")[0]} -> HTTP {e.code} {json.dumps(detail)[:300]}') from None


# ---------- Strava ----------
def strava_token(tok):
    s = tok.get('strava')
    if not s:
        return None
    if s.get('expires_at', 0) > time.time() + 300:
        return s['access_token']
    r = http('POST', 'https://www.strava.com/oauth/token', {
        'client_id': os.environ['STRAVA_CLIENT_ID'], 'client_secret': os.environ['STRAVA_CLIENT_SECRET'],
        'grant_type': 'refresh_token', 'refresh_token': s['refresh_token']})
    tok['strava'] = {k: r[k] for k in ('access_token', 'refresh_token', 'expires_at')}
    save_tokens(tok)  # keep the newest refresh token right away
    return r['access_token']


def strava_sync(tok, changed):
    at = strava_token(tok)
    if not at:
        print('Strava: not connected yet, skipped')
        return
    H = {'Authorization': f'Bearer {at}'}
    rides = json.loads((DATA / 'rides.json').read_text())
    have = {r.get('strava_id') for r in rides}
    last = max((r['date'] for r in rides), default='2026-11-20')
    after = int(dt.datetime.fromisoformat(last).replace(tzinfo=LOCAL_TZ).timestamp()) - 86400
    acts = http('GET', f'https://www.strava.com/api/v3/athlete/activities?after={after}&per_page=50', headers=H) or []
    ss_path = DATA / 'sweet_spot_extra.json'
    ss = json.loads(ss_path.read_text()) if ss_path.exists() else []
    ss_keys = {r['key'] for r in ss}
    week = {r['date']: r for r in json.loads((DATA / 'week.json').read_text())}
    new = 0
    for a in sorted(acts, key=lambda a: a['start_date_local']):
        if a.get('sport_type', a.get('type')) not in ('Ride', 'VirtualRide') or a['id'] in have:
            continue
        if not a.get('device_watts'):
            print(f'Strava: activity on {a["start_date_local"][:10]} has no power meter data, skipped')
            continue
        d = a['start_date_local'][:10]
        indoor = a.get('sport_type', a.get('type')) == 'VirtualRide' or bool(a.get('trainer'))
        np_ = a.get('weighted_average_watts') or a.get('average_watts')
        rides.append(dict(date=d, strava_id=a['id'], name=a.get('name', ''), indoor=indoor,
                          moving_h=round(a['moving_time'] / 3600, 3), np=round(np_) if np_ else None,
                          avg_w=round(a.get('average_watts') or 0, 1), avg_hr=a.get('average_heartrate'),
                          max_hr=a.get('max_heartrate'), max_w=a.get('max_watts'),
                          km=round(a.get('distance', 0) / 1000, 2), np_source='strava weighted average'))
        new += 1
        # sweet-spot laps: 8-40 min at 215-250 W
        laps = http('GET', f'https://www.strava.com/api/v3/activities/{a["id"]}/laps', headers=H) or []
        n = 0
        plan = (week.get(d) or {}).get('plan', '').lower()
        for lap in laps:
            m = lap.get('moving_time', 0) / 60
            w = lap.get('average_watts') or 0
            if 8 <= m <= 40 and 215 <= w <= 250:
                n += 1
                key = f'{d} #{n}'
                if key in ss_keys:
                    continue
                kind = 'Planned session' if 'sweet spot' in plan else 'Unplanned'
                ss.append(dict(key=key, date=d, session=f'{kind}, {"indoor" if indoor else "outdoor"}', effort=n,
                               minutes=round(m, 1), avg_w=round(w, 1), avg_hr=lap.get('average_heartrate'),
                               max_hr=lap.get('max_heartrate'),
                               terrain='Climb' if (lap.get('total_elevation_gain') or 0) >= 60 else 'Flat',
                               in_band=224 <= w <= 240))
                ss_keys.add(key)
    if new:
        rides.sort(key=lambda r: r['date'])
        (DATA / 'rides.json').write_text(json.dumps(rides, indent=1, ensure_ascii=False))
        ss_path.write_text(json.dumps(ss, indent=1, ensure_ascii=False))
        changed.append(f'{new} ride(s)')
    print(f'Strava: {new} new ride(s)')


# ---------- WHOOP ----------
def whoop_token(tok):
    w = tok.get('whoop')
    if not w:
        return None
    if w.get('expires_at', 0) > time.time() + 300:
        return w['access_token']
    r = http('POST', 'https://api.prod.whoop.com/oauth/oauth2/token', {
        'client_id': os.environ['WHOOP_CLIENT_ID'], 'client_secret': os.environ['WHOOP_CLIENT_SECRET'],
        'grant_type': 'refresh_token', 'refresh_token': w['refresh_token'], 'scope': 'offline'})
    tok['whoop'] = {'access_token': r['access_token'], 'refresh_token': r['refresh_token'],
                    'expires_at': int(time.time()) + int(r.get('expires_in', 3600))}
    save_tokens(tok)  # WHOOP invalidates the old refresh token, so save the new one first
    return r['access_token']


def whoop_list(path, H, start):
    out, nxt = [], None
    for _ in range(5):
        q = {'limit': 25, 'start': start}
        if nxt:
            q['nextToken'] = nxt
        r = http('GET', f'https://api.prod.whoop.com/developer/v2/{path}?' + urllib.parse.urlencode(q), headers=H) or {}
        out += r.get('records', [])
        nxt = r.get('next_token')
        if not nxt:
            break
    return out


def whoop_sync(tok, changed):
    at = whoop_token(tok)
    if not at:
        print('WHOOP: not connected yet, skipped')
        return
    H = {'Authorization': f'Bearer {at}'}
    rows = json.loads((DATA / 'whoop.json').read_text())
    have = {r['date'] for r in rows}
    last = max(have)
    start = (dt.datetime.fromisoformat(last) - dt.timedelta(days=2)).strftime('%Y-%m-%dT00:00:00.000Z')
    recs = whoop_list('recovery', H, start)
    sleeps = {s['id']: s for s in whoop_list('activity/sleep', H, start) if not s.get('nap')}
    new = 0
    for r in sorted(recs, key=lambda x: x.get('created_at', '')):
        sc = r.get('score') or {}
        s = sleeps.get(r.get('sleep_id'))
        if r.get('score_state') != 'SCORED' or not s or (s.get('score_state') != 'SCORED'):
            continue
        off = s.get('timezone_offset') or '+08:00'
        sign = 1 if off[0] == '+' else -1
        tz = dt.timezone(sign * dt.timedelta(hours=int(off[1:3]), minutes=int(off[4:6])))
        st = dt.datetime.fromisoformat(s['start'].replace('Z', '+00:00')).astimezone(tz)
        en = dt.datetime.fromisoformat(s['end'].replace('Z', '+00:00')).astimezone(tz)
        d = en.date().isoformat()
        if d in have:
            continue
        ss = (s.get('score') or {})
        stg = ss.get('stage_summary') or {}
        bh = st.hour + st.minute / 60
        bh = bh - 24 if bh > 12 else bh
        rows.append(dict(date=d, recovery=round(sc['recovery_score']), rhr=round(sc['resting_heart_rate']),
                         hrv=round(sc['hrv_rmssd_milli'], 1), bedtime=st.strftime('%H:%M'), bed_h=round(bh, 2),
                         asleep_h=round((stg.get('total_in_bed_time_milli', 0) - stg.get('total_awake_time_milli', 0)) / 3.6e6, 2),
                         sleep_perf=round(ss.get('sleep_performance_percentage') or 0),
                         consistency=round(ss.get('sleep_consistency_percentage') or 0)))
        have.add(d)
        new += 1
    if new:
        rows.sort(key=lambda r: r['date'])
        (DATA / 'whoop.json').write_text(json.dumps(rows, indent=0))
        changed.append(f'{new} WHOOP morning(s)')
    print(f'WHOOP: {new} new morning(s)')



# ---------- per-ride pro metrics (power curve, IF, VI, kJ, carbs, zones, decoupling) ----------
def ftp_now():
    import re
    m = re.search(r'^FTP\s*=\s*(\d+)', (ROOT / 'build.py').read_text(), flags=re.M)
    return int(m.group(1)) if m else 255


def strava_metrics(tok, changed, limit=30):
    at = strava_token(tok)
    if not at:
        return
    sys.path.insert(0, str(ROOT / 'scripts'))
    import metrics as M
    H = {'Authorization': f'Bearer {at}'}
    path = DATA / 'ride_metrics.json'
    store = json.loads(path.read_text()) if path.exists() else {}
    since = int(time.time()) - 92 * 86400
    acts = []
    for page in (1, 2, 3):
        batch = http('GET', f'https://www.strava.com/api/v3/athlete/activities?after={since}&per_page=100&page={page}', headers=H) or []
        acts += batch
        if len(batch) < 100:
            break
    todo = [a for a in sorted(acts, key=lambda a: a['start_date_local'], reverse=True)
            if a.get('sport_type', a.get('type')) in ('Ride', 'VirtualRide') and a.get('device_watts')
            and str(a['id']) not in store]
    ftp = ftp_now()
    done = 0
    for a in todo[:limit]:
        st = http('GET', f'https://www.strava.com/api/v3/activities/{a["id"]}/streams?keys=time,watts,heartrate&key_by_type=true', headers=H) or {}
        t = (st.get('time') or {}).get('data')
        w = (st.get('watts') or {}).get('data')
        hr = (st.get('heartrate') or {}).get('data')
        if not t or not w:
            store[str(a['id'])] = {'date': a['start_date_local'][:10], 'skip': 'no power stream'}
            continue
        m = M.ride_metrics(t, w, hr, ftp)
        if not m:
            store[str(a['id'])] = {'date': a['start_date_local'][:10], 'skip': 'too short'}
            continue
        m.update(date=a['start_date_local'][:10], name=a.get('name', ''), ftp=ftp,
                 indoor=a.get('sport_type', a.get('type')) == 'VirtualRide' or bool(a.get('trainer')),
                 max_w=a.get('max_watts'))
        store[str(a['id'])] = m
        done += 1
    if done:
        path.write_text(json.dumps(store, separators=(',', ':')))
        changed.append(f'{done} ride metric(s)')
    print(f'Metrics: {done} ride(s) analysed, {max(0, len(todo) - limit)} left for the next run')

def main():
    if not os.environ.get('TOKEN_KEY', '').strip():
        print('Not set up yet: add the TOKEN_KEY secret')
        return
    tok = load_tokens()
    changed = []
    errors = []
    for name, fn in (('Strava', strava_sync), ('Metrics', strava_metrics), ('WHOOP', whoop_sync)):
        try:
            fn(tok, changed)
        except Exception as e:  # keep going so one service failing doesn't block the other
            errors.append(f'{name}: {e}')
            print(f'{name} failed: {e}')
    print('Changes: ' + (', '.join(changed) or 'none'))
    if errors and not changed:
        sys.exit(1)


if __name__ == '__main__':
    main()
