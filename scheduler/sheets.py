from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]


def build_clients(credentials_path: str):
    creds = service_account.Credentials.from_service_account_file(
        credentials_path, scopes=SCOPES
    )
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    return sheets, drive


def fetch_with_grid(sheets_service, spreadsheet_id: str) -> dict:
    """Fetch a spreadsheet including grid data (cell values + formatting)."""
    return (
        sheets_service.spreadsheets()
        .get(spreadsheetId=spreadsheet_id, includeGridData=True)
        .execute()
    )


def fetch_metadata(sheets_service, spreadsheet_id: str) -> dict:
    """Fetch a spreadsheet's metadata only (no grid data)."""
    return (
        sheets_service.spreadsheets()
        .get(spreadsheetId=spreadsheet_id, includeGridData=False)
        .execute()
    )
