"""CTF Radar entry point: fetch, filter, persist, notify."""
from __future__ import annotations

import html
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.ctftime import fetch_events
from src.telegram_notify import send_telegram

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.json"
DATA_DIR = ROOT / "data"
EVENTS_PATH = DATA_DIR / "events.json"


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None


def searchable_text(event: dict[str, Any]) -> str:
    parts = [
        str(event.get("title") or ""),
        str(event.get("description") or ""),
        str(event.get("format") or ""),
        str(event.get("restrictions") or ""),
    ]
    organizers = event.get("organizers") or []
    if isinstance(organizers, list):
        parts.extend(str(x.get("name", "") if isinstance(x, dict) else x) for x in organizers)
    return " ".join(parts).casefold()


def category_matches(event: dict[str, Any], config: dict[str, Any]) -> list[str]:
    haystack = searchable_text(event)
    matched = []
    enabled = set(config.get("categories", ["osint", "steganography"]))
    for category in ("osint", "steganography"):
        if category not in enabled:
            continue
        terms = config.get("keywords", {}).get(category, [])
        if any(str(term).casefold() in haystack for term in terms if str(term).strip()):
            matched.append(category)
    return matched


def is_online(event: dict[str, Any]) -> bool:
    # CTFtime's API commonly represents this field as a boolean.
    onsite = event.get("onsite")
    if isinstance(onsite, bool):
        return not onsite
    if isinstance(onsite, (int, float)):
        return onsite == 0
    if isinstance(onsite, str):
        value = onsite.strip().casefold()
        if value in {"false", "0", "no", "online"}:
            return True
        if value in {"true", "1", "yes", "onsite", "on-site", "in-person"}:
            return False
    # Unknown format: be conservative because the user requested online-only.
    return False


def event_id(event: dict[str, Any]) -> str:
    value = event.get("id")
    if value is not None:
        return str(value)
    return str(event.get("ctftime_url") or event.get("url") or event.get("title") or "unknown")


def normalize_event(event: dict[str, Any], config: dict[str, Any]) -> dict[str, Any] | None:
    if config.get("require_online", True) and not is_online(event):
        return None

    matched = category_matches(event, config)
    if not matched:
        return None

    start = parse_datetime(event.get("start"))
    finish = parse_datetime(event.get("finish"))
    official_url = event.get("url") or event.get("ctftime_url") or ""
    ctftime_url = event.get("ctftime_url") or ""
    event_format = str(event.get("format") or "Unknown")
    return {
        "id": event_id(event),
        "title": str(event.get("title") or "Untitled CTF"),
        "url": str(official_url),
        "ctftime_url": str(ctftime_url),
        "start": start.isoformat() if start else None,
        "finish": finish.isoformat() if finish else None,
        "categories": matched,
        "format": event_format,
        "online": True,
        "weight": event.get("weight"),
        "participants": event.get("participants"),
        "location": str(event.get("location") or ""),
        "description": str(event.get("description") or "")[:1500],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def load_existing() -> dict[str, Any]:
    if not EVENTS_PATH.exists():
        return {"updated_at": None, "events": [], "notified_ids": []}
    try:
        with EVENTS_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("events.json must be an object")
        data.setdefault("events", [])
        data.setdefault("notified_ids", [])
        return data
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        print(f"Could not read existing data ({exc}); starting fresh.")
        return {"updated_at": None, "events": [], "notified_ids": []}


def format_date(value: str | None) -> str:
    if not value:
        return "не указано"
    parsed = parse_datetime(value)
    if not parsed:
        return "не указано"
    return parsed.strftime("%d.%m.%Y %H:%M UTC")


def telegram_message(event: dict[str, Any]) -> str:
    title = html.escape(event["title"])
    categories = ", ".join(event["categories"]).upper()
    url = html.escape(event.get("url") or event.get("ctftime_url") or "", quote=True)
    lines = [
        "🎯 <b>Новый CTF найден — CTF Radar</b>",
        f"<b>{title}</b>",
        f"Категории: {html.escape(categories)}",
        f"Начало: {format_date(event.get('start'))}",
        f"Окончание: {format_date(event.get('finish'))}",
        "Формат: онлайн",
    ]
    if url:
        lines.append(f'<a href="{url}">Страница соревнования</a>')
    if event.get("ctftime_url") and event.get("ctftime_url") != event.get("url"):
        ctftime_url = html.escape(event["ctftime_url"], quote=True)
        lines.append(f'<a href="{ctftime_url}">CTFtime</a>')
    lines.append("\nПроверь категории и условия участия на официальной странице.")
    return "\n".join(lines)


def run() -> None:
    config = load_config()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    old = load_existing()
    old_events = {str(e.get("id")): e for e in old.get("events", []) if e.get("id") is not None}
    previously_notified = set(str(x) for x in old.get("notified_ids", []))

    raw_events = fetch_events(
        days_ahead=int(config.get("days_ahead", 45)),
        limit=int(config.get("max_events", 100)),
    )
    normalized = []
    for raw in raw_events:
        try:
            event = normalize_event(raw, config)
            if event:
                normalized.append(event)
        except Exception as exc:
            print(f"Skipping malformed event: {exc}")

    # Preserve old records in the display history if they are still relevant to the feed.
    merged = dict(old_events)
    for event in normalized:
        merged[event["id"]] = event

    def sort_key(e: dict[str, Any]) -> str:
        return str(e.get("start") or "9999")

    events = sorted(merged.values(), key=sort_key)
    first_run = old.get("updated_at") is None
    notify_ids = set(previously_notified)
    if first_run and not config.get("notify_on_first_run", False):
        notify_ids.update(e["id"] for e in normalized)
        print("First run: existing matches are saved without Telegram notifications.")
    else:
        for event in normalized:
            if event["id"] not in notify_ids:
                try:
                    sent = send_telegram(telegram_message(event))
                    if sent:
                        notify_ids.add(event["id"])
                    else:
                        print(f"Notification not marked as sent for {event['id']}; it can be retried after Telegram is configured.")
                except Exception as exc:
                    print(f"Telegram notification failed for {event['id']}: {exc}")

    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "CTFtime API",
        "events": events,
        "notified_ids": sorted(notify_ids),
    }
    temp_path = EVENTS_PATH.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(EVENTS_PATH)
    print(f"Fetched {len(raw_events)} events; {len(normalized)} matched enabled categories and online filter.")
    print(f"Saved {len(events)} total events to {EVENTS_PATH}")


if __name__ == "__main__":
    run()
