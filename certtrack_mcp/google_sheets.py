from __future__ import annotations
import os
from typing import List, Dict, Any, Optional
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
TOKEN_PATH = os.path.join("certtrack_mcp", "token.json")

def _creds():
    if not os.path.exists(TOKEN_PATH):
        raise FileNotFoundError("token.json no encontrado (ejecuta authorize_google.py).")
    return Credentials.from_authorized_user_file(TOKEN_PATH, [SHEETS_SCOPE])

def get_sheets_service():
    return build("sheets", "v4", credentials=_creds())

def read_range(spreadsheet_id: str, rng: str) -> List[List[str]]:
    svc = get_sheets_service()
    resp = svc.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=rng).execute()
    return resp.get("values", [])

def append_rows(spreadsheet_id: str, rng_start: str, rows: List[List[Any]]) -> Dict[str, Any]:
    svc = get_sheets_service()
    body = {"values": rows}
    req = svc.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=rng_start,                 # e.g., "Master!A1"
        valueInputOption="USER_ENTERED", # respeta formatos de la hoja
        insertDataOption="INSERT_ROWS",
        body=body
    )
    return req.execute()
