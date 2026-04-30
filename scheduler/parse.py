import colorsys
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

_TIME_TOKEN_RE = re.compile(r"^\s*(\d{1,2})(?::(\d{2}))?\s*([ap]m)?\s*$", re.IGNORECASE)


def parse_time(token: str) -> str:
    """'8AM' / '8:30pm' / '12:00pm' → '08:00' / '20:30' / '12:00' (24h)."""
    t = token.strip().lower()
    t = t.replace("midnight", "12am").replace("noon", "12pm")
    t = t.replace(" ", "").replace(".", "")
    m = _TIME_TOKEN_RE.match(t)
    if not m:
        raise ValueError(f"Cannot parse time: {token!r}")
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    meridiem = (m.group(3) or "").lower()
    if meridiem == "pm" and hour != 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
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
    """Read the WEEKLY CONFLICTS tab. Returns (dancers, excluded_times).

    Each Dancer has an `availability` dict keyed by (day, start, end) for every
    column where the dancer can mark a conflict. `excluded_times` is the list of
    (day, start, end) tuples for columns labeled with config.excluded_slot_keywords
    (e.g. COMPANY) — candidate slots overlapping these are skipped (mandatory
    company-wide events, not for scheduling).
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

    day_row = _row_values(rowdata, config.dancer_day_row - 1)
    time_row = _row_values(rowdata, config.dancer_time_row - 1)
    excluded_kw = [kw.lower() for kw in (getattr(config, "excluded_slot_keywords", []) or [])]

    available_columns: list[tuple[int, str, str, str]] = []  # (col_idx, day, start, end)
    excluded_times: list[tuple[str, str, str]] = []          # (day, start, end)
    for col_idx in range(max(len(day_row), len(time_row))):
        day_text = _cell_text(day_row[col_idx]) if col_idx < len(day_row) else ""
        time_text = _cell_text(time_row[col_idx]) if col_idx < len(time_row) else ""
        if not day_text or not time_text:
            continue
        day_norm = _normalize_day_label(day_text)
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
    return dancers, excluded_times


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
