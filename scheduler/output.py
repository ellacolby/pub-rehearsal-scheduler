from googleapiclient.errors import HttpError

from .model import Avail, Slot
from .solve import Schedule


class OutputSetupNeeded(RuntimeError):
    """Raised when the user needs to create an output sheet and paste its ID."""


# ---- Public API --------------------------------------------------------------

def write_schedules_to_sheet(
    sheets_service,
    drive_service,
    schedules: list[Schedule],
    *,
    share_email: str,
    existing_id: str = "",
) -> str:
    """Write each schedule to its own tab in a Google Sheet.

    If `existing_id` is provided, replaces all its tabs with fresh ones.
    Otherwise tries to create a new spreadsheet — but service accounts often
    can't create files (no Drive home), in which case we raise OutputSetupNeeded.
    """
    if not schedules:
        raise ValueError("No schedules to write")

    if existing_id:
        spreadsheet_id = existing_id
        _replace_all_tabs(sheets_service, spreadsheet_id, schedules)
    else:
        try:
            spreadsheet_id = _create_new_spreadsheet(sheets_service, schedules)
        except HttpError as e:
            if e.resp.status in (403, 404):
                raise OutputSetupNeeded(
                    "The service account couldn't create a new Google Sheet "
                    "(service accounts often lack Drive storage). "
                    "Manual setup: create a blank Google Sheet, share it with "
                    "the service account email as Editor, and paste its ID into "
                    "config.toml under [sheets].output."
                ) from e
            raise
        if share_email:
            try:
                _share_with_user(drive_service, spreadsheet_id, share_email)
            except HttpError:
                pass  # Best-effort; user already has the URL printed below

    _populate_tabs(sheets_service, spreadsheet_id, schedules)
    return spreadsheet_id


# ---- Spreadsheet creation ----------------------------------------------------

def _create_new_spreadsheet(sheets_service, schedules: list[Schedule]) -> str:
    sheet_specs = [{"properties": {"title": "Summary"}}]
    for i in range(len(schedules)):
        sheet_specs.append({"properties": {"title": f"Option {i + 1}"}})
    body = {
        "properties": {"title": "PUB Schedule Options"},
        "sheets": sheet_specs,
    }
    result = sheets_service.spreadsheets().create(body=body).execute()
    return result["spreadsheetId"]


def _share_with_user(drive_service, spreadsheet_id: str, email: str) -> None:
    drive_service.permissions().create(
        fileId=spreadsheet_id,
        body={"type": "user", "role": "writer", "emailAddress": email},
        sendNotificationEmail=False,
    ).execute()


def _replace_all_tabs(sheets_service, spreadsheet_id: str, schedules: list[Schedule]) -> None:
    """Wipe all existing tabs and replace with fresh Summary + Option tabs.

    Sheets requires the workbook to always have at least one tab, so we:
      1. Rename all existing tabs to unique placeholder names.
      2. Add the new tabs (no name conflicts now).
      3. Delete the renamed placeholders.
    """
    meta = sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    existing = meta.get("sheets", [])

    if existing:
        rename_requests = [
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": s["properties"]["sheetId"],
                        "title": f"_old_{i}_{s['properties']['sheetId']}",
                    },
                    "fields": "title",
                }
            }
            for i, s in enumerate(existing)
        ]
        sheets_service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": rename_requests}
        ).execute()

    new_titles = ["Summary"] + [f"Option {i + 1}" for i in range(len(schedules))]
    add_requests = [{"addSheet": {"properties": {"title": t}}} for t in new_titles]
    sheets_service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id, body={"requests": add_requests}
    ).execute()

    if existing:
        delete_requests = [
            {"deleteSheet": {"sheetId": s["properties"]["sheetId"]}}
            for s in existing
        ]
        sheets_service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": delete_requests}
        ).execute()


# ---- Cell writing ------------------------------------------------------------

def _populate_tabs(sheets_service, spreadsheet_id: str, schedules: list[Schedule]) -> None:
    data = []
    data.append({
        "range": "Summary!A1",
        "values": _summary_rows(schedules),
    })
    for i, sched in enumerate(schedules):
        data.append({
            "range": f"Option {i + 1}!A1",
            "values": _option_rows(i + 1, sched),
        })
    sheets_service.spreadsheets().values().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"valueInputOption": "RAW", "data": data},
    ).execute()

    # Bold the header rows on each tab
    sheet_id_map = _get_sheet_ids(sheets_service, spreadsheet_id)
    bold_requests = []
    for title, sid in sheet_id_map.items():
        bold_requests.append(_bold_first_row_request(sid))
    if bold_requests:
        sheets_service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": bold_requests}
        ).execute()


def _get_sheet_ids(sheets_service, spreadsheet_id: str) -> dict[str, int]:
    meta = sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    return {
        s["properties"]["title"]: s["properties"]["sheetId"]
        for s in meta.get("sheets", [])
    }


def _bold_first_row_request(sheet_id: int) -> dict:
    return {
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 0,
                "endRowIndex": 1,
            },
            "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
            "fields": "userEnteredFormat.textFormat.bold",
        }
    }


# ---- Row builders ------------------------------------------------------------

def _summary_rows(schedules: list[Schedule]) -> list[list]:
    rows = [[
        "Option", "Misses (red)", "Movable (orange)",
        "Unscheduled dances", "Penalty score",
    ]]
    for i, sched in enumerate(schedules):
        rows.append([
            f"Option {i + 1}",
            sched.total_red,
            sched.total_orange,
            len(sched.unscheduled),
            sched.total_penalty,
        ])
    rows.append([])
    rows.append(["Lower penalty = better. Open each Option tab for full details."])
    return rows


def _option_rows(option_num: int, schedule: Schedule) -> list[list]:
    rows: list[list] = []
    rows.append([
        f"Option {option_num}",
        f"misses: {schedule.total_red}",
        f"movable: {schedule.total_orange}",
        f"unscheduled: {len(schedule.unscheduled)}",
        f"penalty: {schedule.total_penalty}",
    ])
    rows.append([])
    rows.append(["Schedule"])
    rows.append(["Day", "Time", "Room", "Dance", "Priority", "Misses (red)", "Movable (orange)"])
    for entry in _entries_sorted(schedule):
        rows.append([
            entry.slot.day_of_week,
            _format_time_range(entry.slot.start, entry.slot.end),
            entry.slot.room,
            entry.dance.name,
            entry.dance.priority,
            len(entry.misses),
            len(entry.movable),
        ])

    if schedule.unscheduled:
        rows.append([])
        rows.append(["Unscheduled dances (no available slot left)"])
        rows.append(["Dance", "Priority"])
        for d in schedule.unscheduled:
            rows.append([d.name, d.priority])

    rows.append([])
    rows.append(["Dancers who would miss / have a conflict"])
    rows.append(["Dance", "Day", "Time", "Room", "Dancer", "Status"])
    any_problems = False
    for entry in _entries_sorted(schedule):
        for m in entry.misses:
            any_problems = True
            rows.append([
                entry.dance.name,
                entry.slot.day_of_week,
                _format_time_range(entry.slot.start, entry.slot.end),
                entry.slot.room,
                m.dancer_display,
                "would miss (red)",
            ])
        for m in entry.movable:
            any_problems = True
            rows.append([
                entry.dance.name,
                entry.slot.day_of_week,
                _format_time_range(entry.slot.start, entry.slot.end),
                entry.slot.room,
                m.dancer_display,
                "movable conflict (orange)",
            ])
    if not any_problems:
        rows.append(["— no conflicts in this option —"])

    unknowns = sorted({u for e in schedule.entries for u in e.unknown_dancers})
    if unknowns:
        rows.append([])
        rows.append(["Casting names not found in availability sheet"])
        for name in unknowns:
            rows.append([name])

    return rows


# ---- Misc helpers ------------------------------------------------------------

_DAY_ORDER = {
    "Sunday": 0, "Monday": 1, "Tuesday": 2, "Wednesday": 3,
    "Thursday": 4, "Friday": 5, "Saturday": 6,
}


def _entries_sorted(schedule: Schedule):
    return sorted(
        schedule.entries,
        key=lambda e: (_DAY_ORDER.get(e.slot.day_of_week, 99), e.slot.start, e.slot.room),
    )


def _format_time_range(start: str, end: str) -> str:
    from .model import _pretty_time
    return f"{_pretty_time(start)}-{_pretty_time(end)}"


def spreadsheet_url(spreadsheet_id: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
