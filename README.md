# PUB Rehearsal Scheduler

Generates rehearsal schedules for Princeton University Ballet by matching dances
to rooms + time slots based on dancer availability. Reads three Google Sheets
(dancer conflicts, room availability, casting), runs a constraint solver, and
writes the top-N schedule options to a Google Sheet (one tab per option).

## Setup

### 1. Service account (one-time)

1. Open <https://console.cloud.google.com/> and create a new project (e.g. `pub-scheduler`).
2. Enable both APIs:
   - <https://console.cloud.google.com/apis/library/sheets.googleapis.com>
   - <https://console.cloud.google.com/apis/library/drive.googleapis.com>
3. APIs & Services → Credentials → **Create Credentials → Service Account**.
   Name it `scheduler-bot`, skip optional roles, click Done.
4. Open the service account → **Keys → Add Key → Create new key → JSON**. Download.
5. Move the downloaded file into this project root and rename it `credentials.json`.
6. Copy the service account's email (ends in `.iam.gserviceaccount.com`) — you'll
   paste it into share dialogs in the next steps.

### 2. Share the input sheets with the service account

Open each of these in Drive, click **Share**, paste the SA email, set role to **Viewer**:

- Dancer conflicts (the `WEEKLY CONFLICTS` workbook)
- Room availability (one tab per day-of-week)
- Casting

### 3. Create an output sheet and share it

Service accounts can't reliably create new files in Drive, so create the output
sheet manually one time:

1. Go to <https://docs.google.com/spreadsheets/u/0/create>, name it (e.g.
   "PUB Schedule Options").
2. Click **Share**, paste the SA email, set role to **Editor**.
3. Copy the spreadsheet ID from the URL (the long string between `/d/` and `/edit`).
4. You'll paste it into `config.toml` in the next step.

### 4. Python environment

Requires Python 3.11+ (uses built-in `tomllib`).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 5. Configure

```bash
cp config.example.toml config.toml
```

In `config.toml`, fill in:

- `[sheets].dancer_availability`, `room_availability`, `casting` — IDs of your three input sheets
- `[sheets].output` — ID of the output sheet you created in step 3
- `share_with_email` — your email (so the SA tries to share the output back to you)

Most other settings have sensible defaults; see "Configuration reference" below
if you need to tune anything.

### 6. Run

```bash
python -m scheduler
```

The script prints a summary to the terminal and rewrites the output sheet with
fresh tabs. Each subsequent run overwrites that same sheet.

## How scheduling works

### Candidate slots

The script ignores the dancer sheet's column times for slot definition — those
are conflict-tracking buckets, not rehearsal definitions. Instead:

1. For each tab in the room sheet (`Monday`, `Tuesday`, …), every 30-min cell
   labeled `PUB` is a reserved time block in that room.
2. Contiguous PUB cells are merged into blocks.
3. Each block is cut into all valid 1-hour and 1.5-hour candidate slots
   (configurable via `slot_durations_minutes`). The solver picks a non-overlapping
   subset.

Slots overlapping a column labeled `COMPANY` (or any keyword in
`excluded_slot_keywords`) are dropped — those are mandatory all-company
rehearsals where dances can't be scheduled.

### Dancer availability

Each cell in the dancer sheet is classified by background color:

| Color | Meaning | Effect |
|-------|---------|--------|
| Green | Available | No penalty |
| Orange / yellow | Partial / movable conflict | Small penalty per dancer per slot |
| Red | Unavailable | Large penalty (counted as a "miss") |
| White / no color | Unknown | Treated as available, no penalty |

For each candidate slot, a dancer's status is the **worst** availability across
any conflict-column overlapping that slot's time on that day. If a slot falls
outside any column the dancer answered for, the dancer is treated as available
there.

### Hard constraints

- **One dance per slot**: a (room, day, time) cell holds at most one dance.
- **No room collisions**: even with sliding 1-hour and 1.5-hour windows, no two
  dances overlap inside the same room.
- **No dancer collisions**: a dancer can't be in two dances at overlapping times,
  in any rooms.

### Objective

A weighted sum over all `(dance, slot)` assignments, multiplied by each dance's
priority:

```
priority(d) × (
    conflict_penalty(d, s)            # red & orange
    − unscheduled_bonus               # being scheduled is much better than not
    − duration_bonus × extra_30min    # prefer longer slots when possible
)
```

In words, the solver prefers schedules that:

1. **Schedule every dance** (vastly more important than anything else).
2. **Avoid red conflicts**, then **orange conflicts**.
3. **Use longer (1.5-hour) slots** instead of leaving gaps in PUB-reserved time.

Priorities scale all three: a dance with `priority = 5` is roughly five times
"louder" in each.

### Top-N options

After finding the optimal schedule, the solver excludes that exact assignment
and re-solves, repeating until it has up to `num_options` distinct schedules.
You can compare them on the Summary tab and pick whichever miss list looks best.

### Unscheduled dances

If PUB's reserved room hours can't fit every dance (e.g. 12 dances but only
~9 non-overlapping room-hours), some dances will appear in the **Unscheduled**
section instead. Use priorities to control which dances get bumped.

## Configuration reference (`config.toml`)

```toml
credentials_path  = "credentials.json"
share_with_email  = "you@example.com"

[sheets]
dancer_availability = "..."   # spreadsheet ID
room_availability   = "..."
casting             = "..."
output              = "..."   # required — create manually and paste the ID

[tabs]
dancer_weekly_tab = "WEEKLY CONFLICTS"

[parsing]
# 1-indexed rows/columns in the dancer sheet
dancer_day_row        = 4
dancer_time_row       = 5
dancer_first_data_row = 6
dancer_name_col       = 2

# Room sheet: rooms in row 1, time labels start in row 2 (one per 30 min)
room_name_row       = 1
room_first_time_row = 2
pub_label           = "PUB"

# Drop dancer-sheet columns whose label contains any of these (case-insensitive)
excluded_slot_keywords = ["COMPANY"]

# Casting: row of dance/choreographer names, then row dancers begin at
casting_dance_name_row   = 2
casting_first_dancer_row = 6

[name_aliases]
# Map a casting-sheet name to a dancer's full name in the availability sheet.
# Useful for nicknames or typos.
"Maddie"  = "MADELINE ROHDE"
"Madddie" = "MADELINE ROHDE"

[priorities]
# Higher = more important (default 1). Use for pieces that missed last week,
# are less polished, etc. Keys are dance/choreographer names (case-insensitive).
# "GISELE" = 5
# "BLAISE" = 3

[solver]
slot_durations_minutes = [60, 90]   # 1-hour and 1.5-hour slot lengths
orange_penalty         = 1
red_penalty            = 100
num_options            = 5
time_limit_seconds     = 30
allow_twice_per_week   = false      # stretch goal — not yet implemented
```

## Sheet format expectations

### Room availability

- One tab per day-of-week, named `Monday`, `Tuesday`, … (anything that starts
  with a day name works).
- Row 1 = column headers including room names (e.g. `Bloomberg`, `Roberts`).
- Column A = time labels in 30-min increments (e.g. `8:00am-8:30am`).
- A cell containing `PUB` means PUB has the room reserved for that 30-min block.
  Other group names (Disiac, BodyHype, etc.) are ignored.

### Dancer conflicts

- Tab named `WEEKLY CONFLICTS` (configurable).
- Row 4 = day-of-week labels per column (`MONDAY`, `TUESDAY`, …).
- Row 5 = time-of-day per column (e.g. `8:30pm - 9:30pm`).
  A column whose label contains `COMPANY` (case-insensitive) is treated as a
  mandatory company-wide block — no dance scheduled during it.
- Row 6 onward = one row per dancer; column B is the dancer's full name.
- Cell color (green/orange/red) is what counts; text is informational.

### Casting

- Each column = one dance.
- Row 2 = dance/choreographer name (the dance ID).
- Row 6 onward = dancer names (`First` or `First L`). The list ends at the
  first empty cell in the column.

## Common workflows

### Mark a dance as priority

Edit `config.toml`:

```toml
[priorities]
"GISELE" = 5
```

Re-run. The dance now wins the longest available slot at a conflict-free time
and is the last to be bumped if room hours run out.

### Add an alias for a misspelled or nicknamed dancer

```toml
[name_aliases]
"Maddie" = "MADELINE ROHDE"
```

The casting name `Maddie` will resolve to the availability row for
`MADELINE ROHDE`.

### Compare options

Open the output sheet and look at the **Summary** tab:

| Option | Misses (red) | Movable (orange) | Unscheduled | Penalty |
|--------|--------------|------------------|-------------|---------|

Each Option tab shows the full schedule, the list of dancers who would miss,
and which dances were left unscheduled.
