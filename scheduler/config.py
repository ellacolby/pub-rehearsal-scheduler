import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path


def extract_sheet_id(url_or_id: str) -> str:
    """Accept either a bare spreadsheet ID or a Google Sheets URL.
    Returns just the ID. Lets non-tech users paste a URL straight from the browser."""
    s = (url_or_id or "").strip()
    m = re.search(r"/d/([a-zA-Z0-9_-]+)", s)
    if m:
        return m.group(1)
    return s


def app_dir() -> Path:
    """Directory next to which `config.toml` and `credentials.json` should live.

    When running as a frozen PyInstaller executable, this is the directory
    containing the .exe / binary itself, so the user can drop config files
    next to the binary they double-clicked. Otherwise, current working dir."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def resolve_path(maybe_relative: str) -> Path:
    """Resolve `maybe_relative` against app_dir() if not already absolute."""
    p = Path(maybe_relative)
    if p.is_absolute():
        return p
    return (app_dir() / p).resolve()


@dataclass
class Config:
    credentials_path: str
    share_with_email: str

    sheet_dancer: str
    sheet_room: str
    sheet_casting: str
    sheet_output: str

    dancer_weekly_tab: str
    target_week_start: str  # YYYY-MM-DD; if set, monthly-tab overrides for that week stack onto weekly

    dancer_day_row: int
    dancer_time_row: int
    dancer_first_data_row: int
    dancer_name_col: int

    room_name_row: int
    room_first_time_row: int
    pub_label: str

    casting_dance_name_row: int
    casting_first_dancer_row: int

    excluded_slot_keywords: list[str]
    name_aliases: dict[str, str]
    priorities: dict[str, int]

    slot_durations_minutes: list[int]

    orange_penalty: int
    red_penalty: int
    num_options: int
    time_limit_seconds: int
    allow_twice_per_week: bool


def load_config(path: str = "config.toml") -> Config:
    p = resolve_path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"{p} not found. Copy config.example.toml to config.toml next to the "
            "executable (or current directory) and fill it in."
        )
    with p.open("rb") as f:
        data = tomllib.load(f)

    sheets = data["sheets"]
    tabs = data["tabs"]
    parsing = data["parsing"]
    solver = data["solver"]

    return Config(
        credentials_path=data["credentials_path"],
        share_with_email=data.get("share_with_email", ""),
        sheet_dancer=extract_sheet_id(sheets["dancer_availability"]),
        sheet_room=extract_sheet_id(sheets["room_availability"]),
        sheet_casting=extract_sheet_id(sheets["casting"]),
        sheet_output=extract_sheet_id(sheets.get("output", "")),
        dancer_weekly_tab=tabs["dancer_weekly_tab"],
        target_week_start=str(tabs.get("target_week_start", "")).strip(),
        dancer_day_row=parsing["dancer_day_row"],
        dancer_time_row=parsing["dancer_time_row"],
        dancer_first_data_row=parsing["dancer_first_data_row"],
        dancer_name_col=parsing["dancer_name_col"],
        room_name_row=parsing["room_name_row"],
        room_first_time_row=parsing["room_first_time_row"],
        pub_label=parsing["pub_label"],
        casting_dance_name_row=parsing["casting_dance_name_row"],
        casting_first_dancer_row=parsing["casting_first_dancer_row"],
        excluded_slot_keywords=parsing.get("excluded_slot_keywords", ["COMPANY"]),
        name_aliases=data.get("name_aliases", {}),
        priorities={k: int(v) for k, v in (data.get("priorities") or {}).items()},
        slot_durations_minutes=solver.get("slot_durations_minutes", [60, 90]),
        orange_penalty=solver["orange_penalty"],
        red_penalty=solver["red_penalty"],
        num_options=solver["num_options"],
        time_limit_seconds=solver["time_limit_seconds"],
        allow_twice_per_week=solver["allow_twice_per_week"],
    )
