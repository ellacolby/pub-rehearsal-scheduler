import colorsys
import datetime
import re
from typing import Optional

from .model import Avail, DAYS_OF_WEEK, Dance, Dancer, Slot


# ============================ Color classification =============================

def classify_color(rgb: Optional[dict]) -> Avail:
    """Map a Sheets-API backgroundColor dict to an availability level."""
    if not rgb:
        return Avail.UNKNOWN
    r = float(rgb.get("red", 0.0))
    g = float(rgb.get("green", 0.0))
    b = float(rgb.get("blue", 0.0))

    if min(r, g, b) > 0.92:
        return Avail.UNKNOWN

    h, s, _ = colorsys.rgb_to_hsv(r, g, b)
    if s < 0.12:
        return Avail.UNKNOWN

    # Hue is in [0, 1]: 0 = red, ~0.167 = yellow/orange, ~0.333 = green
    if h < 0.07 or h > 0.95:
        return Avail.RED
    if h < 0.20:
        return Avail.ORANGE
    if h < 0.45:
        return Avail.GREEN
    return Avail.UNKNOWN


# ================================ Time parsing =================================

_TIME_TOKEN_RE = re.compile(r"^\s*(\d{1,2})(?::(\d{2}))?\s*([ap]m?)?\s*$", re.IGNORECASE)


def parse_time(token: str) -> str:
    """'8AM' / '8:30pm' / '9p' / '12:00pm' → '08:00' / '20:30' / '21:00' / '12:00' (24h).
    Single-letter 'p' or 'a' is accepted as shorthand for pm/am."""
    t = token.strip().lower()
    t = t.replace("midnight", "12am").replace("noon", "12pm")
    t = t.replace(" ", "").replace(".", "")
    m = _TIME_TOKEN_RE.match(t)
    if not m:
        raise ValueError(f"Cannot parse time: {token!r}")
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    meridiem = (m.group(3) or "").lower()
    if meridiem.startswith("p") and hour != 12:
        hour += 12
    elif meridiem.startswith("a") and hour == 12:
        hour = 0
    return f"{hour:02d}:{minute:02d}"


def parse_time_range(s: str) -> tuple[str, str]:
    """Find a time range inside a string. Tolerates surrounding text like
    'COMPANY 1:00pm - 3:00pm' and shorthand like '8 - 9pm'.
    Returns (start_24h, end_24h)."""
    raw = s.strip()
    raw = re.sub(r"\bmidnight\b", "12am", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\bnoon\b", "12pm", raw, flags=re.IGNORECASE)

    # Both endpoints have a meridiem
    m = re.search(
        r"(\d{1,2}(?::\d{2})?\s*[ap]\.?m\.?)\s*[-–—]\s*(\d{1,2}(?::\d{2})?\s*[ap]\.?m\.?)",
        raw, re.IGNORECASE,
    )
    if m:
        return parse_time(m.group(1)), parse_time(m.group(2))

    # Only end has a meridiem
    m = re.search(
        r"(\d{1,2}(?::\d{2})?)\s*[-–—]\s*(\d{1,2}(?::\d{2})?\s*[ap]\.?m\.?)",
        raw, re.IGNORECASE,
    )
    if m:
        end_tok = m.group(2)
        mer = re.search(r"[ap]\.?m\.?", end_tok, re.IGNORECASE)
        meridiem = mer.group(0) if mer else ""
        return parse_time(m.group(1) + meridiem), parse_time(end_tok)

    raise ValueError(f"Cannot parse time range: {s!r}")


def enumerate_subtimes(start_24h: str, end_24h: str, step_minutes: int = 30) -> list[str]:
    """Return list of 'HH:MM' start-times covering [start, end), step-aligned from start.
    e.g., 20:30 → 21:30 with step=30 → ['20:30', '21:00']."""
    sh, sm = map(int, start_24h.split(":"))
    eh, em = map(int, end_24h.split(":"))
    s_min = sh * 60 + sm
    e_min = eh * 60 + em
    if e_min <= s_min:
        e_min += 24 * 60  # crosses midnight
    out: list[str] = []
    cur = s_min
    while cur < e_min:
        h = (cur // 60) % 24
        m = cur % 60
        out.append(f"{h:02d}:{m:02d}")
        cur += step_minutes
    return out


# ================================== Names ====================================

def split_name(name: str) -> tuple[str, str]:
    """'AIMEE ZOU' → ('Aimee', 'Z'). 'Lucy C' → ('Lucy', 'C'). 'Alex' → ('Alex', '')."""
    parts = name.strip().split()
    if not parts:
        return ("", "")
    first = parts[0].strip().title()
    if len(parts) >= 2:
        last_clean = re.sub(r"[^A-Za-z]", "", parts[-1])
        return (first, last_clean[:1].upper() if last_clean else "")
    return (first, "")


# =============================== Grid helpers =================================

def _row_values(rowdata: list, row_idx: int) -> list:
    if row_idx < 0 or row_idx >= len(rowdata):
        return []
    return rowdata[row_idx].get("values", []) or []


def _cell_text(cell: dict) -> str:
    return (cell.get("formattedValue") or "").strip()


def _cell_bg(cell: dict) -> Optional[dict]:
    fmt = cell.get("effectiveFormat") or {}
    return fmt.get("backgroundColor")


def _normalize_day_label(s: str) -> Optional[str]:
    s_clean = s.strip().lower()
    for day in DAYS_OF_WEEK:
        if s_clean.startswith(day.lower()):
            return day
    return None


def _day_of_week_from_tab(tab_name: str) -> Optional[str]:
    return _normalize_day_label(tab_name)


def _find_sheet(workbook: dict, tab_name: str) -> Optional[dict]:
    target = tab_name.strip().lower()
    for sheet in workbook.get("sheets", []):
        if sheet.get("properties", {}).get("title", "").strip().lower() == target:
            return sheet
    return None


# =========================== Dancer availability ==============================

def parse_dancer_availability(
    workbook: dict, config
) -> tuple[list[Dancer], list[tuple[str, str, str]]]:
    """Read WEEKLY CONFLICTS, plus any monthly tabs that contain dates inside
    `config.target_week_start`'s week. Returns (dancers, excluded_times).

    Per-cell availability stacks: at each (day, start, end) key, the worst
    severity across the weekly tab and any matching monthly tab wins. The
    overlap-aware lookup in `dancer_availability_at` further takes the worst
    across all overlapping conflict columns.
    """
    sheet = _find_sheet(workbook, config.dancer_weekly_tab)
    if sheet is None:
        raise RuntimeError(
            f"Tab {config.dancer_weekly_tab!r} not found in dancer sheet."
        )
    data = sheet.get("data", [])
    if not data:
        return [], []
    rowdata = data[0].get("rowData", []) or []

    available_columns, excluded_times = _parse_conflict_columns(rowdata, config, target_dates=None)

    name_col = config.dancer_name_col - 1
    dancers: list[Dancer] = []
    for row_idx in range(config.dancer_first_data_row - 1, len(rowdata)):
        row = _row_values(rowdata, row_idx)
        if not row or name_col >= len(row):
            continue
        full_name = _cell_text(row[name_col])
        if not full_name:
            continue
        first, initial = split_name(full_name)
        d = Dancer(full_name=full_name, first_name=first, last_initial=initial)
        for col_idx, day, start, end in available_columns:
            avail = classify_color(_cell_bg(row[col_idx])) if col_idx < len(row) else Avail.UNKNOWN
            d.availability[(day, start, end)] = avail
        dancers.append(d)

    # Apply monthly-tab overrides for the target week (if configured)
    target_week_start = getattr(config, "target_week_start", "") or ""
    if target_week_start:
        target_dates = _week_dates(target_week_start)
        if target_dates:
            n = _apply_monthly_overrides(workbook, config, dancers, excluded_times, target_dates)
            if n:
                print(
                    f"Applied {n} one-off conflict cell(s) from monthly tabs "
                    f"for week of {target_week_start}."
                )
        else:
            print(
                f"WARNING: target_week_start={target_week_start!r} is not a valid YYYY-MM-DD date; "
                "monthly overrides skipped."
            )

    return dancers, excluded_times


def _parse_conflict_columns(
    rowdata: list,
    config,
    target_dates: Optional[list[datetime.date]] = None,
) -> tuple[list[tuple[int, str, str, str]], list[tuple[str, str, str]]]:
    """Parse the day-row and time-row of a conflicts tab.
    Returns (available_columns, excluded_times).

    If target_dates is None, day-cells are read as day-of-week names (weekly tab).
    If target_dates is provided, day-cells are read as dates (e.g. 'Sun 4/26'),
    and only columns whose date is in target_dates are included; the day-of-week
    is derived from the matched date.
    """
    day_row = _row_values(rowdata, config.dancer_day_row - 1)
    time_row = _row_values(rowdata, config.dancer_time_row - 1)
    excluded_kw = [kw.lower() for kw in (getattr(config, "excluded_slot_keywords", []) or [])]

    available_columns: list[tuple[int, str, str, str]] = []
    excluded_times: list[tuple[str, str, str]] = []
    for col_idx in range(max(len(day_row), len(time_row))):
        day_text = _cell_text(day_row[col_idx]) if col_idx < len(day_row) else ""
        time_text = _cell_text(time_row[col_idx]) if col_idx < len(time_row) else ""
        if not day_text or not time_text:
            continue
        if target_dates is None:
            day_norm = _normalize_day_label(day_text)
        else:
            matched = _match_monthly_date(day_text, target_dates)
            if matched is None:
                continue
            day_norm = matched.strftime("%A")
        if day_norm is None:
            continue
        try:
            start, end = parse_time_range(time_text)
        except ValueError:
            continue
        if any(kw in time_text.lower() for kw in excluded_kw):
            excluded_times.append((day_norm, start, end))
        else:
            available_columns.append((col_idx, day_norm, start, end))
    return available_columns, excluded_times


def _apply_monthly_overrides(
    workbook: dict,
    config,
    dancers: list[Dancer],
    excluded_times: list[tuple[str, str, str]],
    target_dates: list[datetime.date],
) -> int:
    """Walk monthly conflict tabs (calendar layout) and stack their notes onto
    each dancer's availability. Returns the count of overrides applied.

    For each calendar cell falling on a target date, free-text notes are split on
    ';' and parsed for:
      - "OOT"                 → dancer unavailable all day (RED 00:00–23:59)
      - "X-Y" / "Xpm-Ypm"     → dancer unavailable for that range
      - "X pm onward / eod"   → dancer unavailable from X until end of day
    Dancer names are matched by first name (case-insensitive) at the start of
    each phrase. Notes that don't contain a recognized dancer or time are skipped.
    """
    weekly_lower = config.dancer_weekly_tab.strip().lower()
    by_first: dict[str, list[Dancer]] = {}
    for d in dancers:
        by_first.setdefault(d.first_name.lower(), []).append(d)

    # Also let calendar text reuse name_aliases (e.g. "Maddie" → MADELINE ROHDE).
    aliases = getattr(config, "name_aliases", {}) or {}
    by_full_name = {d.full_name.lower(): d for d in dancers}
    for alias_key, full_name in aliases.items():
        target = by_full_name.get(str(full_name).strip().lower())
        if target is None:
            continue
        alias_first = str(alias_key).strip().split()[0].lower() if alias_key.strip() else ""
        if alias_first and target not in by_first.get(alias_first, []):
            by_first.setdefault(alias_first, []).append(target)

    n_applied = 0
    for sheet in workbook.get("sheets", []):
        title = sheet.get("properties", {}).get("title", "").strip()
        if title.lower() == weekly_lower:
            continue
        data = sheet.get("data", [])
        if not data:
            continue
        rowdata = data[0].get("rowData", []) or []

        for dancer, day_name, start, end in _parse_calendar_overrides(
            rowdata, title, target_dates, by_first
        ):
            key = (day_name, start, end)
            existing = dancer.availability.get(key, Avail.UNKNOWN)
            if _AVAIL_SEVERITY[Avail.RED] > _AVAIL_SEVERITY.get(existing, 0):
                dancer.availability[key] = Avail.RED
                n_applied += 1
    return n_applied


# Each calendar day cell occupies 2 columns: label on the left, date number on the right.
_CALENDAR_DAY_COLS = [
    (0, 1, "Sunday"),
    (2, 3, "Monday"),
    (4, 5, "Tuesday"),
    (6, 7, "Wednesday"),
    (8, 9, "Thursday"),
    (10, 11, "Friday"),
    (12, 13, "Saturday"),
]


def _parse_calendar_overrides(
    rowdata: list,
    tab_title: str,
    target_dates: list[datetime.date],
    by_first: dict[str, list[Dancer]],
) -> list[tuple[Dancer, str, str, str]]:
    """Parse one calendar-layout monthly tab. Returns (dancer, day_of_week, start_24h, end_24h)
    tuples for each conflict whose date is in target_dates."""
    tab_year, tab_month = _parse_calendar_month(tab_title)
    if tab_year is None or tab_month is None:
        return []

    target_set = set(target_dates)
    out: list[tuple[Dancer, str, str, str]] = []

    for ridx, row_struct in enumerate(rowdata):
        row = row_struct.get("values", []) or []
        active_cells: list[tuple[int, str]] = []  # (label_col, day_name)
        for label_col, date_col, day_name in _CALENDAR_DAY_COLS:
            if date_col >= len(row):
                continue
            txt = _cell_text(row[date_col])
            if not txt.isdigit():
                continue
            day_num = int(txt)
            if not (1 <= day_num <= 31):
                continue
            try:
                date = datetime.date(tab_year, tab_month, day_num)
            except ValueError:
                continue
            if date in target_set:
                active_cells.append((label_col, day_name))
        if not active_cells:
            continue

        # Walk subsequent rows until the next date row
        for nr in range(ridx + 1, len(rowdata)):
            n_row = rowdata[nr].get("values", []) or []
            if _looks_like_calendar_date_row(n_row):
                break
            for label_col, day_name in active_cells:
                if label_col >= len(n_row):
                    continue
                text = _cell_text(n_row[label_col])
                if not text:
                    continue
                for fragment in re.split(r"[;\n]+", text):
                    fragment = fragment.strip()
                    if fragment:
                        out.extend(_parse_conflict_phrase(fragment, day_name, by_first))
    return out


def _looks_like_calendar_date_row(row: list) -> bool:
    digit_cells = 0
    for cell in row:
        txt = _cell_text(cell)
        if txt.isdigit() and 1 <= int(txt) <= 31:
            digit_cells += 1
    return digit_cells >= 4


def _parse_calendar_month(tab_title: str) -> tuple[Optional[int], Optional[int]]:
    months = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
    }
    title_lower = tab_title.lower()
    month = None
    for name, num in months.items():
        if name in title_lower:
            month = num
            break
    if month is None:
        return None, None
    year_match = re.search(r"(20\d{2})", tab_title)
    year = int(year_match.group(1)) if year_match else datetime.date.today().year
    return year, month


_NAME_TOKEN_RE = re.compile(r"[A-Za-z]+")
_OOT_RE = re.compile(r"\bOOT\b|\ball\s*day\b", re.IGNORECASE)
_RANGE_RE = re.compile(
    r"(\d{1,2})(?::(\d{2}))?\s*([ap]m?)?\s*[-–—]\s*(\d{1,2})(?::(\d{2}))?\s*([ap]m?)?",
    re.IGNORECASE,
)
_FUZZY_END_RANGE_RE = re.compile(
    r"(\d{1,2})(?::(\d{2}))?\s*([ap]m?)\s*[-–—]\s*(?:late|eod|end\s+of\s+day|midnight)",
    re.IGNORECASE,
)
_EOD_RE = re.compile(
    r"(\d{1,2})(?::(\d{2}))?\s*([ap]m?)\s*(?:on(?:ward)?s?\b|to\s*eod\b|\beod\b|end\s+of\s+day)",
    re.IGNORECASE,
)


def _resolve_name_token(token: str, by_first: dict[str, list[Dancer]]) -> list[Dancer]:
    """Resolve a name-ish token to a list of matching dancers.
    Tries: exact first-name match, then 'firstinitial' split (e.g., 'lucyp' → Lucy P)."""
    direct = by_first.get(token.lower(), [])
    if direct:
        return direct
    # Try splitting "lucyp" → "lucy" + "p"
    for split_pt in range(len(token) - 1, 1, -1):
        first_part = token[:split_pt].lower()
        initial_part = token[split_pt:]
        if len(initial_part) != 1 or not initial_part.isalpha():
            continue
        first_candidates = by_first.get(first_part, [])
        if not first_candidates:
            continue
        refined = [c for c in first_candidates if c.last_initial == initial_part.upper()]
        if len(refined) == 1:
            return refined
    return []


def _parse_conflict_phrase(
    text: str,
    day_name: str,
    by_first: dict[str, list[Dancer]],
) -> list[tuple[Dancer, str, str, str]]:
    """Parse a single conflict phrase. Returns list of (dancer, day_name, start_24h, end_24h)."""
    text = text.strip()
    if not text:
        return []

    # Pull leading dancer-name tokens (separated by whitespace, '/', '&', ',', or 'and')
    matched: list[Dancer] = []
    rest = text
    while True:
        m = _NAME_TOKEN_RE.match(rest)
        if not m:
            break
        token = m.group(0)
        candidates = _resolve_name_token(token, by_first)
        if not candidates:
            break
        if len(candidates) == 1:
            matched.append(candidates[0])
        else:
            # Ambiguous first name — try next char as last-initial
            next_pos = m.end()
            if next_pos < len(rest) and rest[next_pos].isalpha():
                initial = rest[next_pos].upper()
                refined = [c for c in candidates if c.last_initial == initial]
                if len(refined) == 1:
                    matched.append(refined[0])
                    rest = rest[next_pos + 1:].lstrip(" /&,")
                    sep = re.match(r"\s*(?:and\b|&|,|/)\s*", rest, re.IGNORECASE)
                    if sep:
                        rest = rest[sep.end():]
                        continue
                    break
            matched.extend(candidates)  # apply to all if still ambiguous
        rest = rest[m.end():].lstrip(" /&,")
        sep = re.match(r"\s*(?:and\b|&|,|/)\s*", rest, re.IGNORECASE)
        if sep:
            rest = rest[sep.end():]
            continue
        break

    if not matched:
        return []

    rest = rest.strip()

    if _OOT_RE.search(rest):
        return [(d, day_name, "00:00", "23:59") for d in matched]

    # "Xpm-late", "Xpm-eod", "Xpm-midnight" — start to end-of-day
    fuzzy = _FUZZY_END_RANGE_RE.search(rest)
    if fuzzy:
        try:
            start_str = f"{fuzzy.group(1)}{':' + fuzzy.group(2) if fuzzy.group(2) else ''}{fuzzy.group(3).lower()}"
            return [(d, day_name, parse_time(start_str), "23:59") for d in matched]
        except ValueError:
            pass

    rng = _RANGE_RE.search(rest)
    if rng:
        try:
            start_24h, end_24h = _parse_range_match(rng)
            return [(d, day_name, start_24h, end_24h) for d in matched]
        except ValueError:
            pass

    eod = _EOD_RE.search(rest)
    if eod:
        try:
            start_24h = _parse_eod_match(eod)
            return [(d, day_name, start_24h, "23:59") for d in matched]
        except ValueError:
            pass

    return []


def _parse_range_match(m: re.Match) -> tuple[str, str]:
    s_h, s_m, s_mer, e_h, e_m, e_mer = m.groups()
    start_str = f"{s_h}{':' + s_m if s_m else ''}{(s_mer or '').lower()}"
    end_str = f"{e_h}{':' + e_m if e_m else ''}{(e_mer or '').lower()}"
    if not s_mer and not e_mer:
        # Neither has meridiem — assume PM (most rehearsal conflicts are evenings)
        start_str += "pm"
        end_str += "pm"
    elif not s_mer:
        start_str += (e_mer or "").lower()
    elif not e_mer:
        end_str += (s_mer or "").lower()
    return parse_time(start_str), parse_time(end_str)


def _parse_eod_match(m: re.Match) -> str:
    h, mn, mer = m.groups()
    s = f"{h}{':' + mn if mn else ''}{mer.lower()}"
    return parse_time(s)


def _week_dates(start_iso: str) -> list[datetime.date]:
    try:
        start = datetime.date.fromisoformat(start_iso)
    except ValueError:
        return []
    return [start + datetime.timedelta(days=i) for i in range(7)]


# ============================== Room availability =============================

def parse_room_availability(
    workbook: dict,
    config,
    excluded_times: list[tuple[str, str, str]],
    *,
    slot_minutes_options: list[int] | None = None,
    cell_step_minutes: int = 30,
) -> list[Slot]:
    """Cut every contiguous PUB block into candidate slots of each length in
    `slot_minutes_options` (default from config, e.g. [60, 90]). Skip slots that
    overlap any time in `excluded_times` (e.g. mandatory COMPANY rehearsals)."""
    if slot_minutes_options is None:
        slot_minutes_options = list(getattr(config, "slot_durations_minutes", [60, 90]))
    pub_cells: dict[tuple[str, str], set[str]] = {}  # (day, room) → set of cell-start "HH:MM"

    for sheet in workbook.get("sheets", []):
        title = sheet.get("properties", {}).get("title", "")
        day = _day_of_week_from_tab(title)
        if day is None:
            continue
        data = sheet.get("data", [])
        if not data:
            continue
        rowdata = data[0].get("rowData", []) or []

        room_row = _row_values(rowdata, config.room_name_row - 1)
        rooms_by_col: dict[int, str] = {}
        for col_idx, cell in enumerate(room_row):
            if col_idx == 0:
                continue
            text = _cell_text(cell)
            if text:
                rooms_by_col[col_idx] = text

        for row_idx in range(config.room_first_time_row - 1, len(rowdata)):
            row_values = _row_values(rowdata, row_idx)
            if not row_values:
                continue
            time_text = _cell_text(row_values[0]) if row_values else ""
            if not time_text:
                continue
            try:
                start, _end = parse_time_range(time_text)
            except ValueError:
                continue
            for col_idx, room_name in rooms_by_col.items():
                if col_idx >= len(row_values):
                    continue
                if _cell_text(row_values[col_idx]).upper() == config.pub_label.upper():
                    pub_cells.setdefault((day, room_name), set()).add(start)

    candidates: list[Slot] = []
    for (day, room), starts in pub_cells.items():
        for s_start, s_end in _pub_block_to_slots(starts, slot_minutes_options, cell_step_minutes):
            if any(
                ex_day == day and _times_overlap(s_start, s_end, ex_start, ex_end)
                for (ex_day, ex_start, ex_end) in excluded_times
            ):
                continue
            candidates.append(Slot(day_of_week=day, start=s_start, end=s_end, room=room))
    return candidates


# ----- block-cutting helpers -----

def _pub_block_to_slots(
    starts: set[str], slot_minutes_options: list[int], step_minutes: int
) -> list[tuple[str, str]]:
    """Given 30-min PUB cell starts in the same (day, room), enumerate every
    candidate slot of any length in `slot_minutes_options` that fits inside a
    contiguous run of PUB cells. The solver later picks a non-overlapping subset."""
    if not starts:
        return []
    mins = sorted(_to_minutes(s) for s in starts)
    blocks: list[list[int]] = []
    cur = [mins[0]]
    for m in mins[1:]:
        if m == cur[-1] + step_minutes:
            cur.append(m)
        else:
            blocks.append(cur)
            cur = [m]
    blocks.append(cur)

    out: set[tuple[str, str]] = set()
    for slot_minutes in slot_minutes_options:
        cells_per_slot = slot_minutes // step_minutes
        for block in blocks:
            for i in range(len(block) - cells_per_slot + 1):
                start_min = block[i]
                end_min = start_min + slot_minutes
                out.add((_to_hhmm(start_min), _to_hhmm(end_min)))
    return list(out)


def _to_minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _to_hhmm(minutes: int) -> str:
    h = (minutes // 60) % 24
    m = minutes % 60
    return f"{h:02d}:{m:02d}"


def _times_overlap(a_start: str, a_end: str, b_start: str, b_end: str) -> bool:
    """Half-open overlap on 'HH:MM' strings (lex order matches numeric order for fixed width)."""
    return a_start < b_end and b_start < a_end


# ----- dancer availability lookup -----

_AVAIL_SEVERITY = {
    Avail.GREEN: 0,
    Avail.UNKNOWN: 0,
    Avail.ORANGE: 1,
    Avail.RED: 2,
}


def dancer_availability_at(dancer: Dancer, slot: Slot) -> Avail:
    """The dancer's worst availability across any conflict-column overlapping this slot.
    Returns UNKNOWN if no column overlaps (e.g. slot is outside any column the dancer
    answered for)."""
    worst: Optional[Avail] = None
    for (day, c_start, c_end), avail in dancer.availability.items():
        if day != slot.day_of_week:
            continue
        if not _times_overlap(c_start, c_end, slot.start, slot.end):
            continue
        if worst is None or _AVAIL_SEVERITY[avail] > _AVAIL_SEVERITY[worst]:
            worst = avail
    return worst if worst is not None else Avail.UNKNOWN


# ================================== Casting ===================================

def parse_casting(workbook: dict, config) -> list[Dance]:
    """Each non-empty column on each tab is one dance. Header row = dance/choreographer name."""
    all_dances: list[Dance] = []
    for sheet in workbook.get("sheets", []):
        data = sheet.get("data", [])
        if not data:
            continue
        rowdata = data[0].get("rowData", []) or []
        header_row = _row_values(rowdata, config.casting_dance_name_row - 1)

        for col_idx, cell in enumerate(header_row):
            dance_name = _cell_text(cell)
            if not dance_name:
                continue
            dancers: list[str] = []
            for row_idx in range(config.casting_first_dancer_row - 1, len(rowdata)):
                row = _row_values(rowdata, row_idx)
                if col_idx >= len(row):
                    break
                d_name = _cell_text(row[col_idx])
                if not d_name:
                    break
                dancers.append(d_name)
            if dancers:
                all_dances.append(Dance(name=dance_name, dancers=dancers))
    return all_dances


# ========================= Casting ↔ availability =============================

def match_casting_names(
    dances: list[Dance],
    dancers: list[Dancer],
    aliases: Optional[dict[str, str]] = None,
) -> tuple[dict[str, Dancer], list[str]]:
    """Resolve casting names to availability dancers.

    Match order:
      1. Explicit alias (casting name → availability full name) — for nicknames/typos
      2. First-name match (case-insensitive). Last-initial disambiguates duplicates.

    Returns (lookup, unmatched_names).
    """
    aliases = aliases or {}
    by_full_name = {d.full_name.lower(): d for d in dancers}
    by_first: dict[str, list[Dancer]] = {}
    for d in dancers:
        by_first.setdefault(d.first_name.lower(), []).append(d)

    # Normalize alias keys for case-insensitive lookup
    alias_lower = {k.lower(): v for k, v in aliases.items()}

    lookup: dict[str, Dancer] = {}
    unmatched: list[str] = []
    seen_unmatched: set[str] = set()

    for dance in dances:
        for casting_name in dance.dancers:
            if casting_name in lookup:
                continue
            alias_target = alias_lower.get(casting_name.lower())
            if alias_target:
                d = by_full_name.get(alias_target.lower())
                if d is not None:
                    lookup[casting_name] = d
                    continue

            target_first, target_initial = split_name(casting_name)
            candidates = by_first.get(target_first.lower(), [])
            if target_initial:
                candidates = [c for c in candidates if c.last_initial == target_initial]
            if len(candidates) == 1:
                lookup[casting_name] = candidates[0]
            else:
                if casting_name not in seen_unmatched:
                    unmatched.append(casting_name)
                    seen_unmatched.add(casting_name)
    return lookup, unmatched
