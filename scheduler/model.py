from dataclasses import dataclass, field
from enum import Enum


class Avail(Enum):
    GREEN = "green"
    ORANGE = "orange"
    RED = "red"
    UNKNOWN = "unknown"


DAYS_OF_WEEK = (
    "Sunday", "Monday", "Tuesday", "Wednesday",
    "Thursday", "Friday", "Saturday",
)


@dataclass(frozen=True)
class Slot:
    day_of_week: str   # "Monday"
    start: str         # "20:30" (24-hour)
    end: str           # "21:30"
    room: str          # "Roberts"

    def time_key(self) -> tuple[str, str, str]:
        return (self.day_of_week, self.start, self.end)

    def label(self) -> str:
        return f"{self.day_of_week} {_pretty_time(self.start)}-{_pretty_time(self.end)} @ {self.room}"


@dataclass(frozen=True)
class RehearsalSlot:
    """A canonical rehearsal time block (from the dancer sheet column headers)."""
    day_of_week: str
    start: str   # 24h "HH:MM"
    end: str
    label: str   # original text from the sheet, e.g. "8:30pm - 9:30pm" or "COMPANY 1:00pm - 3:00pm"


@dataclass
class Dance:
    name: str
    dancers: list[str]      # raw casting names ("Lucy C", "Alex")
    priority: int = 1       # higher = more likely scheduled and gets longer slots


@dataclass
class Dancer:
    full_name: str          # "AIMEE ZOU" — as it appears in the availability sheet
    first_name: str         # "Aimee"
    last_initial: str       # "Z" (or "" if not present)
    availability: dict[tuple[str, str, str], Avail] = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        if self.last_initial:
            return f"{self.first_name} {self.last_initial}"
        return self.first_name


def _pretty_time(t: str) -> str:
    """'20:30' -> '8:30pm'."""
    try:
        h, m = t.split(":")
        h_int = int(h)
        m_int = int(m)
    except (ValueError, AttributeError):
        return t
    suffix = "am" if h_int < 12 else "pm"
    h12 = h_int % 12
    if h12 == 0:
        h12 = 12
    if m_int == 0:
        return f"{h12}{suffix}"
    return f"{h12}:{m_int:02d}{suffix}"
