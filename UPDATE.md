# Daily dashboard update (for the morning check-in)

The site is `index.html`, built by `python3 build.py` from `template.html` and `data/*.json`.
Netlify publishes the repository root on every push. There is no build step on Netlify, so
`index.html` must be rebuilt and committed.

## Each morning

1. **Rides.** From Strava `get-recent-activities`, take every Ride or VirtualRide dated after
   the last date in `data/rides.json`. Skip runs and other sports. For each ride:
   - `get-activity-details` → moving time, distance, average watts, average and max HR.
   - `get-activity-streams` with `types: ["time","watts"]`, `resolution: "medium"`,
     `summary_only: true` → `statistics.watts.normalized_power` (np) and `statistics.watts.max` (max_w).
   - Append to `data/rides.json`:
     `{"date","strava_id","name","indoor" (true for VirtualRide),"moving_h","np","avg_w","avg_hr","max_hr","max_w","km"}`
   - Do not add a ride that has no power data; note it in the check-in instead.
2. **WHOOP.** Use the structured daily summary (timezone Asia/Singapore), plus `whoop_list_sleeps`
   in structured mode for in-bed and awake milliseconds. Append one row per new morning
   to `data/whoop.json`:
   `{"date" (wake date, local),"recovery","rhr","hrv","bedtime" ("HH:MM" local),"bed_h" (hours after midnight, negative before midnight),"asleep_h" ((in_bed - awake)/3.6e6),"sleep_perf","consistency"}`
   Leave `load_day_before` out; `build.py` fills it.
3. **Plan.** If the coach changes the plan, edit or add rows in `data/week.json`
   (`date, dow, type ("ride"|"rest"), short (a 2–5 word title), plan, planned_h_max, indoor`,
   other fields null/"" and `status: "upcoming"`). Actuals for dates after 20 Nov are filled by
   `build.py` from rides. The "This week's plan" card shows the Mon–Sun week holding the next
   planned day; when a new week starts and it has no rows yet, add that week's 7 rows from the
   training plan, and a one-line summary keyed by its Monday in `data/week_notes.json`.
4. Run `python3 build.py`. It prints CTL, ATL and TSB. It must finish without errors.
5. Commit `data/` and `index.html` with message `Daily update YYYY-MM-DD` and push to `main`.

## Rules
- Only real numbers from Strava and WHOOP. Never invent a value; leave a day out if data is missing.
- No GPS data and no raw WHOOP mode.
- FTP is set in `build.py` (`FTP = 255`). Change it only when the athlete confirms a new FTP.
- `data/static.json` (power curve, durability, sweet spot, weight and so on) is a snapshot from
  20 Nov 2026. It is refreshed by hand in a coaching chat, not here.
