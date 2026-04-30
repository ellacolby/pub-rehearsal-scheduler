import sys
from pathlib import Path

from .config import load_config
from .model import _pretty_time
from .output import OutputSetupNeeded, spreadsheet_url, write_schedules_to_sheet
from .parse import (
    match_casting_names,
    parse_casting,
    parse_dancer_availability,
    parse_room_availability,
)
from .sheets import build_clients, fetch_with_grid
from .solve import solve


def main() -> None:
    cfg = load_config()

    if not Path(cfg.credentials_path).exists():
        sys.exit(
            f"credentials.json not found at {cfg.credentials_path!r}. "
            "Follow the README setup steps to create a service account."
        )

    print("Connecting to Google Sheets…")
    sheets, drive = build_clients(cfg.credentials_path)

    print("Fetching room availability…")
    room_book = fetch_with_grid(sheets, cfg.sheet_room)
    print("Fetching dancer availability…")
    dancer_book = fetch_with_grid(sheets, cfg.sheet_dancer)
    print("Fetching casting…")
    casting_book = fetch_with_grid(sheets, cfg.sheet_casting)

    dancers, excluded_times = parse_dancer_availability(dancer_book, cfg)
    candidate_slots = parse_room_availability(room_book, cfg, excluded_times)
    dances = parse_casting(casting_book, cfg)

    # Apply priorities (case-insensitive match on dance name)
    priority_lower = {k.lower(): v for k, v in cfg.priorities.items()}
    for d in dances:
        d.priority = priority_lower.get(d.name.lower(), 1)
    if any(d.priority != 1 for d in dances):
        boosted = [(d.name, d.priority) for d in dances if d.priority != 1]
        print("Priorities applied:", ", ".join(f"{n}={p}" for n, p in boosted))

    print(
        f"Parsed: {len(candidate_slots)} candidate slots from PUB blocks, "
        f"{len(dancers)} dancers, {len(dances)} dances"
        + (f" (excluding {len(excluded_times)} company-wide time(s))" if excluded_times else "")
    )

    if not candidate_slots:
        sys.exit("No candidate slots found. Check that the room sheet has 'PUB' cells "
                 "and that day-of-week tabs are named like 'Monday May 18th'.")
    if not dancers:
        sys.exit(
            f"No dancers parsed. Check the {cfg.dancer_weekly_tab!r} tab and the "
            "row/column indexes in config.toml."
        )
    if not dances:
        sys.exit("No dances parsed from the casting sheet.")

    lookup, unmatched = match_casting_names(dances, dancers, cfg.name_aliases)
    if unmatched:
        print()
        print("WARNING: these casting names could not be matched to a dancer "
              "(ambiguous or missing):")
        for name in unmatched:
            print(f"  - {name!r}")
        print("These dancers' availability will be ignored when scoring options.")
        print()

    print(f"Solving for top {cfg.num_options} schedule options…")
    schedules = solve(
        dances=dances,
        dancers=dancers,
        candidate_slots=candidate_slots,
        dancer_lookup=lookup,
        orange_penalty=cfg.orange_penalty,
        red_penalty=cfg.red_penalty,
        num_options=cfg.num_options,
        time_limit_seconds=cfg.time_limit_seconds,
    )

    if not schedules:
        sys.exit("Solver returned no feasible schedules. "
                 "Check that there are enough PUB slots for the number of dances.")

    _print_summary(schedules)

    print(f"Writing {len(schedules)} option(s) to Google Sheet…")
    try:
        spreadsheet_id = write_schedules_to_sheet(
            sheets, drive, schedules,
            share_email=cfg.share_with_email,
            existing_id=cfg.sheet_output,
        )
    except OutputSetupNeeded as e:
        print()
        print("=== Output setup needed ===")
        print(str(e))
        print()
        print("Steps:")
        print("  1. https://docs.google.com/spreadsheets/u/0/create — make a blank sheet,")
        print("     name it (e.g. 'PUB Schedule Options').")
        print("  2. Click Share, paste your service account email, set role to **Editor**.")
        print("  3. Copy the spreadsheet ID from the URL (between /d/ and /edit).")
        print("  4. Paste it into config.toml under [sheets].output  and rerun.")
        sys.exit(1)
    url = spreadsheet_url(spreadsheet_id)
    print(f"Done — open: {url}")


def _print_summary(schedules) -> None:
    print()
    print(f"{'Option':<10}{'Misses':>10}{'Movable':>10}{'Unsched':>10}{'Penalty':>12}")
    for i, s in enumerate(schedules):
        print(
            f"{f'Option {i+1}':<10}{s.total_red:>10}{s.total_orange:>10}"
            f"{len(s.unscheduled):>10}{s.total_penalty:>12}"
        )
    print()
    best = schedules[0]
    print(
        f"--- Option 1 details: {best.total_red} miss, {best.total_orange} movable, "
        f"{len(best.unscheduled)} unscheduled ---"
    )
    for entry in sorted(best.entries, key=lambda e: (e.slot.day_of_week, e.slot.start)):
        time_str = f"{_pretty_time(entry.slot.start)}-{_pretty_time(entry.slot.end)}"
        line = f"  {entry.slot.day_of_week} {time_str} @ {entry.slot.room}: {entry.dance.name}"
        if entry.misses:
            line += "  | misses: " + ", ".join(m.dancer_display for m in entry.misses)
        if entry.movable:
            line += "  | movable: " + ", ".join(m.dancer_display for m in entry.movable)
        print(line)
    if best.unscheduled:
        print(f"  Unscheduled: {', '.join(d.name for d in best.unscheduled)}")
    print()


if __name__ == "__main__":
    main()
