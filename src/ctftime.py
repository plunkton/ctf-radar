"""Small client for the public CTFtime events API."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import requests

API_URL = "https://ctftime.org/api/v1/events/"


def fetch_events(days_ahead: int = 45, limit: int = 100) -> list[dict]:
    now = datetime.now(timezone.utc)
    start = int(now.timestamp())
    finish = int((now + timedelta(days=days_ahead)).timestamp())
    params = {"start": start, "finish": finish, "limit": limit}
    headers = {
        "User-Agent": "CTF-Radar/0.1 (personal event discovery tool)",
        "Accept": "application/json",
    }
    response = requests.get(API_URL, params=params, headers=headers, timeout=25)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise ValueError("Unexpected CTFtime API response: expected a JSON list")
    return payload
