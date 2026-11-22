"""Per-ride metrics from Strava streams (power, heart rate, time).

Everything here is computed from the 1-second data, the way TrainingPeaks, WKO and
intervals.icu do it. Carbohydrate use is an estimate (see carbs_g).
"""
import numpy as np

DURS = [1, 5, 10, 15, 30, 60, 120, 180, 300, 480, 600, 720, 900, 1200, 1800, 2400, 3600, 5400]
GAP = 3  # seconds; longer recording gaps are treated as stopped


def series(t, w, hr=None):
    """Return (elapsed 1-s watts with zeros while stopped, moving 1-s watts, moving 1-s HR)."""
    t = np.asarray(t, dtype=int)
    w = np.nan_to_num(np.asarray(w, dtype=float))
    n = int(t[-1]) + 1
    el = np.zeros(n)
    moving = np.zeros(n, dtype=bool)
    h = np.full(n, np.nan)
    hv = None if hr is None else np.asarray(hr, dtype=float)
    for i in range(len(t)):
        a = t[i]
        b = t[i + 1] if i + 1 < len(t) else a + 1
        if b - a <= GAP:
            el[a:b] = w[i]
            moving[a:b] = True
            if hv is not None:
                h[a:b] = hv[i]
        else:
            el[a] = w[i]
            moving[a] = True
            if hv is not None:
                h[a] = hv[i]
    return el, el[moving], h[moving]


def mmp(el):
    cs = np.concatenate([[0.0], np.cumsum(el)])
    out = {}
    for d in DURS:
        if d <= len(el):
            out[str(d)] = round(float(np.max(cs[d:] - cs[:-d]) / d), 1)
    return out


def np_power(mv):
    if len(mv) < 30:
        return float(np.mean(mv)) if len(mv) else 0.0
    r = np.convolve(mv, np.ones(30) / 30, mode='valid')
    return float(np.mean(r ** 4) ** 0.25)


def zones(mv, ftp):
    """Seconds in Coggan power zones Z1-Z7 (as % of FTP)."""
    edges = [0, .55, .75, .90, 1.05, 1.20, 1.50, 99]
    p = mv / ftp
    return [int(np.sum((p >= edges[i]) & (p < edges[i + 1]))) for i in range(7)]


def carbs_g(kj, IF):
    """Rough carbohydrate use: kcal ≈ kJ (≈24% gross efficiency); carb share rises with intensity."""
    share = float(np.interp(IF, [0.5, 0.65, 0.75, 0.85, 0.95], [0.35, 0.5, 0.65, 0.8, 0.9]))
    return round(kj * share / 4)


def decoupling(mv, hrm):
    """Pw:Hr decoupling: efficiency in the 1st vs 2nd half, after a 10-min warm-up."""
    ok = ~np.isnan(hrm)
    if len(mv) < 3600 or ok.mean() < 0.9:
        return None
    p, h = mv[600:], hrm[600:]
    m = len(p) // 2
    def ef(a, b):
        g = ~np.isnan(b) & (b > 60)
        return np.mean(a[g]) / np.mean(b[g]) if g.sum() > 300 else None
    e1, e2 = ef(p[:m], h[:m]), ef(p[m:], h[m:])
    if not e1 or not e2:
        return None
    return round(float((e1 - e2) / e1 * 100), 1)


def ride_metrics(t, w, hr, ftp):
    el, mv, hrm = series(t, w, hr)
    if len(mv) < 300:
        return None
    npw = np_power(mv)
    avg = float(np.mean(mv))
    IF = npw / ftp
    kj = float(np.sum(mv)) / 1000
    vi = npw / avg if avg > 0 else None
    out = dict(moving_s=int(len(mv)), np=round(npw), avg_w=round(avg, 1), IF=round(IF, 3),
               VI=round(vi, 3) if vi else None, kj=round(kj), carbs_g=carbs_g(kj, IF),
               tss=round(len(mv) / 3600 * IF ** 2 * 100), zones=zones(mv, ftp), mmp=mmp(el),
               avg_hr=round(float(np.nanmean(hrm)), 1) if hr is not None and np.isfinite(hrm).any() else None)
    steady = len(mv) >= 3600 and vi is not None and vi <= 1.15 and IF <= 0.85
    out['decoupling'] = decoupling(mv, hrm) if (steady and hr is not None) else None
    return out
