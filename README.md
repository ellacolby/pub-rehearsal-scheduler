# PUB Rehearsal Scheduler

Generates rehearsal schedules for Princeton University Ballet by matching dances
to rooms + time slots based on dancer availability. Reads three Google Sheets
(dancer conflicts, room availability, casting), runs a constraint solver, and
writes the top-N schedule options to a Google Sheet.

---

# 👥 For end-users (you were given a folder)

## What you got

The team admin sent you a file called **`PUB Scheduler.zip`**. Unzip it (just
double-click in Finder) and you'll get a folder:

```
PUB Scheduler/
├── pub-scheduler              ← the program itself
├── Run PUB Scheduler.command  ← double-click this to run it
├── config.toml                ← settings (only edit when something changes)
└── credentials.json           ← Google login key (treat like a password)
```

Drag the unzipped folder somewhere safe — your Desktop or Documents work fine.
Don't break it apart — keep all four files together.

If anything is missing, ask the team admin who built it.

## First time only — get past macOS Gatekeeper

macOS will refuse to run an unsigned program the first time. To get past it:

1. **Right-click** (or two-finger tap) on `Run PUB Scheduler.command`
2. Choose **Open** from the menu
3. macOS will show a warning — click **Open** again
4. Done — you'll never see the warning again on your machine

You may also see the same warning for `pub-scheduler` itself the first time it
launches. Same fix: right-click → Open.

## Generating a schedule (every week)

1. **Make sure the room availability sheet is up to date.** Open the team's room
   sheet in your browser and confirm this week's PUB cells are filled in.
2. **Double-click `Run PUB Scheduler.command`.** A black-and-white Terminal
   window will pop up.
3. **Pick a week** when prompted:
   ```
   Schedule for the week starting (YYYY-MM-DD) [2026-05-04]:
   ```
   - Press **Enter** to use the suggested upcoming Monday.
   - Or type a different Monday's date in the format `YYYY-MM-DD` (e.g.
     `2026-05-11`) and press Enter.
4. **Wait ~10 seconds.** The scheduler talks to Google, runs the solver, and
   prints a summary.
5. **Open the link** it prints at the end (`https://docs.google.com/...`). Each
   tab = one schedule option. The Summary tab compares them.
6. Press Enter to close the Terminal window.

That's it for normal weekly use.

## Marking a dance as priority

If a piece missed last week's rehearsal (or for any other reason needs to be
scheduled first / get the longest slot), tell the scheduler before running.

1. **Open `config.toml` in TextEdit.** (Right-click → Open With → TextEdit.)
2. Find the section that looks like this:
   ```toml
   [priorities]
   # "JACOB" = 5
   # "GISELE" = 4
   ```
3. **Remove the `#` and quotation marks aren't needed:** type the dance name
   (matches the column header in the casting sheet) and a number. Higher number
   = more important. Example after editing:
   ```toml
   [priorities]
   "BLAISE" = 5
   "JACOB" = 3
   ```
4. **Save** (`File` → `Save`, or ⌘S). Close the file.
5. Run the scheduler as usual. The schedule will reflect the new priorities.

To remove a priority later, put a `#` back at the start of its line.

## At the start of a new semester (changing sheets)

Most semesters, your team will **reuse the same Google Sheets** and just update
their contents. In that case you don't need to change anything.

If your team uses **brand-new sheets** for the semester:

1. **Get the new sheet links from the team admin.** You need three URLs:
   - Dancer conflicts sheet
   - Room availability sheet
   - Casting sheet
2. **Make sure the new sheets are shared with the service account.** The team
   admin will know the email — paste it into each sheet's Share dialog as
   **Viewer** access.
3. **Open `config.toml` in TextEdit.** Find the `[sheets]` section:
   ```toml
   [sheets]
   dancer_availability = "https://docs.google.com/spreadsheets/d/.../edit"
   room_availability   = "https://docs.google.com/spreadsheets/d/.../edit"
   casting             = "https://docs.google.com/spreadsheets/d/.../edit"
   output              = "https://docs.google.com/spreadsheets/d/.../edit"
   ```
4. **Replace each URL** between the quotes with the new one. Just paste the
   browser address bar — the rest will figure itself out. Keep the quotes.
5. **Save and close.** The scheduler is ready for the new semester.

`output` is where the schedule options get written. If the team admin set up a
new output sheet, paste its URL here too. Otherwise leave it.

## How to fill out the conflict sheet so the scheduler reads it

The **`WEEKLY CONFLICTS`** tab is structured (one row per dancer, color-coded
cells) — keep doing what you do there.

The **monthly tabs** (e.g. `APRIL CONFLICTS`) are calendar-style with free-text
notes per day. The scheduler reads those notes and turns them into red blocks
in the dancer's grid for that specific date — but only if you write them in a
recognizable format. Cheat sheet:

### What it understands

| Write this | What the scheduler does |
|------------|------------------------|
| `Deeta OOT` | Deeta unavailable all day |
| `Lucy all day` | Lucy unavailable all day |
| `Cici meeting 7-9pm` | Cici unavailable 7pm–9pm |
| `Blaise midterm 9am-12pm` | Blaise unavailable 9am–12pm |
| `Helena 6pm onward` | Helena unavailable 6pm–end of day |
| `Lucy 5pm to eod` | Lucy unavailable 5pm–end of day |
| `Ritika 6pm-late` | Ritika unavailable 6pm–end of day |
| `Ava 7-midnight` | Ava unavailable 7pm–end of day |
| `Rika & Spencer 7-9pm` | both Rika **and** Spencer unavailable 7pm–9pm |
| `lucyp/Lulu/Lilly 7-9pm` | all three unavailable 7pm–9pm |
| `Cici busy 7-9pm; Helena 8-10pm` | two separate conflicts in one cell |

### Tips for writing them

- **First name only** is enough — match what's in the `WEEKLY CONFLICTS` rows.
  If multiple dancers share a first name (e.g. two Lucys), add the last
  initial: `Lucyp` or `Lucy P`.
- **Always include `am` / `pm`** on at least the end of the time range
  (otherwise it assumes PM, which is right for evening conflicts but not
  morning).
- **Separate names** with `&`, `/`, `,`, or `and` — all work.
- **Separate multiple conflicts in one cell** with `;`.
- **OOT** = "out of town" → whole day. `all day` works too.
- The scheduler **ignores** anything it can't make sense of, so notes like
  "thesis due tmrw" don't generate phantom conflicts.

### What it can't read

- Vague terms without times: "Hell week", "busy", "thesis due"
- Multiple ranges in one phrase: `somiya 3:45-5:30 and 8-10pm` — only the
  first range is captured. **Workaround**: split with `;`:
  `somiya 3:45-5:30pm; somiya 8-10pm`
- Made-up nicknames not in the dancer list (fix once in `[name_aliases]`)

When in doubt, run the scheduler — it'll print **"Applied N one-off conflict
cell(s) from monthly tabs"** so you can see how many it caught.

## "Maddie" / "lucyp" / unmatched-name warnings

If the scheduler prints something like:

```
WARNING: these casting names could not be matched to a dancer:
  - 'Maddie'
```

That means the casting sheet has "Maddie" but the dancer-conflicts sheet has
that person under a different name (e.g. "MADELINE ROHDE"). Fix it once in
`config.toml`:

1. Open `config.toml`, find `[name_aliases]`.
2. Add a line in the format `"Casting Name" = "FULL DANCER NAME"`. Example:
   ```toml
   [name_aliases]
   "Maddie"  = "MADELINE ROHDE"
   "Madddie" = "MADELINE ROHDE"
   ```
3. Save.

## Things that go wrong & how to fix them

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Terminal closes instantly | The program crashed on start. Open Terminal manually, drag in the executable, press Enter to see the actual error. | |
| `credentials.json not found` | The JSON key file isn't next to the binary. | Drop it in the same folder as `pub-scheduler`. |
| `403: caller does not have permission` | The service account isn't shared on one of the input sheets. | Open each sheet, **Share**, paste the SA email as Viewer. |
| `No candidate slots found` | No PUB cells in the room sheet for the selected week. | Update the room sheet. |
| `Solver returned no feasible schedules` | Number of dances with rooms too tight. | Live with the unscheduled list, or add more PUB room reservations. |
| Schedule looks wrong / missing dancer | A name didn't match. | Add a `[name_aliases]` entry (see above). |

If you're truly stuck, send the Terminal output to the team admin.

---

# 🛠 For the admin (you set this up)

## One-time setup (you only)

### 1. Create the Google Cloud service account

1. <https://console.cloud.google.com/> → New Project (e.g. `pub-scheduler`).
2. Enable both APIs:
   - <https://console.cloud.google.com/apis/library/sheets.googleapis.com>
   - <https://console.cloud.google.com/apis/library/drive.googleapis.com>
3. APIs & Services → Credentials → Create Service Account → name it `scheduler-bot`.
4. Open the service account → Keys → Add Key → JSON → download.
5. Rename the file `credentials.json`. **Treat it like a password.**
6. Copy the SA email (ends in `.iam.gserviceaccount.com`).

### 2. Set up the sheets

Share each of the **three input sheets** with the SA email as **Viewer**:

- Dancer conflicts
- Room availability
- Casting

Create one **output sheet** (any blank Google Sheet), share with the SA email
as **Editor**, and copy its URL — you'll paste it into `config.toml`.

### 3. Configure

1. `cp config.example.toml config.toml`
2. Open `config.toml` and paste the four sheet URLs into the `[sheets]` section.
3. Set `share_with_email` to the address you'd like the output shared back to.

### 4. Build the executable

```bash
./build.sh
```

This produces a ready-to-share zip at **`dist/PUB Scheduler.zip`** (~63 MB on
macOS arm64). The zip contains:

```
PUB Scheduler/
├── pub-scheduler              ← the binary
├── Run PUB Scheduler.command  ← double-click launcher
├── config.toml                ← from the project root
└── credentials.json           ← from the project root
```

If `config.toml` or `credentials.json` aren't in the project root yet, the
script will skip them with a warning — finish setup, then re-run `./build.sh`.

The binary is platform-specific. To ship a Windows version, run the equivalent
build on a Windows machine.

### 5. Distribute

Send `dist/PUB Scheduler.zip` to teammates via Google Drive / iMessage / a
1Password attachment / etc.

⚠️ Because the zip includes `credentials.json` (the service-account private
key), treat the zip itself like a password — don't post it in a public channel.
For larger teams, prefer 1Password "secure note" attachments or a
permission-controlled Drive folder.

Recipients unzip it, then right-click `Run PUB Scheduler.command` → **Open**.

## Handing off admin to a new person

The Google Cloud project + service account sit under the admin's personal
Google account. When that account expires (e.g. after graduation), the project
disappears and the binary stops working. So **before you leave, transfer the
admin role to someone with a longer-term Princeton account** (an underclassman,
a club tech lead, or — best — a shared club account).

The handoff doesn't touch any code. Steps for the new admin:

1. Run through the **One-time setup** above (sections 1–3) under their own
   Google account: create a new GCP project, enable both APIs, create a service
   account, download `credentials.json`.
2. Open each of the three input sheets (`dancer_availability`, `room_availability`,
   `casting`) and share with the new SA email as **Viewer**.
3. Open the existing output sheet (or create a fresh one) and share with the
   new SA email as **Editor**.
4. Update one line in `config.toml`:
   ```toml
   share_with_email = "their-email@princeton.edu"
   ```
5. Run `./build.sh` to produce a fresh `dist/PUB Scheduler.zip` (with their
   credentials inside) and redistribute.

The sheet IDs in `[sheets]` stay the same as long as the team is using the same
Google Sheets. The dancers' workflow doesn't change at all — they just receive
a new zip and replace their copy.

The outgoing admin can leave their own GCP project running indefinitely as a
safety net, but the team should switch over to the new admin's project so
nothing breaks when the old account is deactivated.

## Running from source (developers)

Requires Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config.example.toml config.toml          # edit it
python -m scheduler                          # same prompts as the binary
```

## How scheduling works (technical detail)

### Candidate slots

Slot definitions come from PUB room reservations, not the dancer sheet's
columns. For each tab in the room sheet (`Monday`, `Tuesday`, …):

1. Every 30-min cell labeled `PUB` is a reserved time block in that room.
2. Contiguous PUB cells are merged into blocks.
3. Each block is sliced into all valid 1-hour and 1.5-hour candidate slots
   (configurable via `slot_durations_minutes`).

The solver then picks a non-overlapping subset.

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
any conflict-column overlapping that slot's time on that day.

### One-off conflicts (monthly tabs)

When `target_week_start` is provided (or chosen at the prompt), the scheduler
also reads the monthly conflict tabs (e.g. `APRIL CONFLICTS`) and stacks any
per-day notes onto the weekly grid. The monthly tabs use a calendar layout —
one cell per date, free-text notes inside. The parser extracts conflicts like:

| Phrase | Effect |
|--------|--------|
| `Deeta OOT` / `Deeta all day` | RED for whole day |
| `Cici meeting 7-9pm` | RED 7pm–9pm |
| `Blaise midterm 9am-12pm` | RED 9am–12pm |
| `Helena 6pm onward` / `Lucy 5pm to eod` | RED start–end of day |
| `Ritika 6pm-late` / `Ava 7-midnight` | RED start–end of day |

Multiple conflicts per cell separated by `;`. Names can be slash- or
ampersand-joined: `Rika & Spencer 9:30-11:30`, `lucyp/Lulu/Lilly 7-9pm`.
Stuck-together first-name + initial like `lucyp` resolves to Lucy P.

Phrases without a recognized first name and time pattern are skipped silently.

### Hard constraints

- **One dance per slot**: a (room, day, time) cell holds at most one dance.
- **No room collisions**: no two dances overlap inside the same room.
- **No dancer collisions**: a dancer can't be in two dances at overlapping
  times, in any rooms.

### Objective

A weighted sum over all `(dance, slot)` assignments, multiplied by each dance's
priority:

```
priority(d) × (
    conflict_penalty(d, s)       # red & orange
    − unscheduled_bonus          # being scheduled is much better than not
    − duration_bonus × extra_30  # prefer longer slots when possible
)
```

The solver prefers schedules that:

1. **Schedule every dance** (vastly more important than anything else).
2. **Avoid red conflicts**, then **orange conflicts**.
3. **Use longer (1.5-hour) slots** instead of leaving gaps in PUB-reserved time.

Priorities scale all three.

### Top-N options

After finding the optimal schedule, the solver excludes that exact assignment
and re-solves, repeating until it has up to `num_options` distinct schedules.
You can compare them on the Summary tab and pick whichever miss list looks best.

### Unscheduled dances

If PUB's reserved room hours can't fit every dance, some appear in the
**Unscheduled** section. Use priorities to control which dances get bumped.

## Configuration reference

See the comments in `config.toml`. Most fields you'll never touch.

## Sheet format expectations

### Room availability

- One tab per day-of-week, named `Monday`, `Tuesday`, … (anything that starts
  with a day name works).
- Row 1 = column headers including room names.
- Column A = time labels in 30-min increments (e.g. `8:00am-8:30am`).
- A cell containing `PUB` means PUB has the room reserved for that 30-min
  block. Other group names are ignored.

### Dancer conflicts

- Tab named `WEEKLY CONFLICTS` (configurable).
- Row 4 = day-of-week labels per column.
- Row 5 = time-of-day per column. Columns whose label contains `COMPANY` are
  treated as mandatory all-company time.
- Row 6 onward = one row per dancer; column B is the dancer's full name.
- Cell color (green/orange/red) is what counts; text is informational.
- Optional monthly tabs (`APRIL CONFLICTS`, etc.) for date-specific overrides
  in calendar layout.

### Casting

- Each column = one dance.
- Row 2 = dance/choreographer name (the dance ID).
- Row 6 onward = dancer names (`First` or `First L`). Stops at the first empty
  cell in the column.
