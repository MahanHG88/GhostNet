import json
import os
import time
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCHEDULE_FILE = os.path.join(BASE_DIR, "schedule.json")

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
FALLBACK_STATUS = "not available at the moment"


def config():
    try:
        with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def now():
    tz_name = config().get("timezone")
    if tz_name and ZoneInfo:
        try:
            return datetime.now(ZoneInfo(tz_name))
        except Exception:
            pass
    return datetime.now()


def _minutes(value):
    try:
        hours, _, mins = str(value).partition(":")
        return int(hours) * 60 + int(mins)
    except (TypeError, ValueError):
        return None


def _window_status(windows, minute_of_day):
    for window in windows:
        start = _minutes(window.get("from"))
        end = _minutes(window.get("to"))
        if start is None or end is None:
            continue
        if start < end:
            inside = start <= minute_of_day < end
        else:
            inside = minute_of_day >= start or minute_of_day < end
        if inside:
            return window.get("status")
    return None


def override_active(override):
    if not override or not override.get("status"):
        return False
    expires_at = override.get("expires_at")
    return not expires_at or expires_at > time.time()


def scheduled_status(when=None):
    when = when or now()
    windows = config().get("weekly", {}).get(DAYS[when.weekday()], [])
    return _window_status(windows, when.hour * 60 + when.minute)


def current_status(override, when=None):
    if override_active(override):
        return override["status"], "manual update"
    scheduled = scheduled_status(when)
    if scheduled:
        return scheduled, "schedule"
    return config().get("default") or FALLBACK_STATUS, "default"


def _status_at(moment, cfg):
    windows = cfg.get("weekly", {}).get(DAYS[moment.weekday()], [])
    return _window_status(windows, moment.hour * 60 + moment.minute) or cfg.get("default") or FALLBACK_STATUS


def next_change(when=None):
    """The next moment her status changes, so 'when is she free?' can be answered without
    handing the model her whole routine."""
    when = when or now()
    cfg = config()
    if not cfg.get("weekly"):
        return None, None

    current = _status_at(when, cfg)
    moments = []
    for offset in (0, 1):
        day = when + timedelta(days=offset)
        for window in cfg.get("weekly", {}).get(DAYS[day.weekday()], []):
            for edge in (_minutes(window.get("from")), _minutes(window.get("to"))):
                if edge is None:
                    continue
                moment = day.replace(hour=edge // 60, minute=edge % 60, second=0, microsecond=0)
                if moment > when:
                    moments.append(moment)

    for moment in sorted(moments):
        status = _status_at(moment, cfg)
        if status != current:
            return moment, status
    return None, None


def availability_hint(when=None):
    when = when or now()
    moment, status = next_change(when)
    if not moment:
        return ""
    label = "today" if moment.date() == when.date() else "tomorrow"
    return "That changes around {:%H:%M} {}, when she is {}.".format(moment, label, status)
