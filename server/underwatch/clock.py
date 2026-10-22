"""Time in the resident's town and the waking schedule."""
from datetime import datetime, timedelta

from .config import TZ
from .settings import sleep_h, wake_h


WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]

MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]


def now():
    return datetime.now(TZ)


def is_awake_time(t=None):
    t = t or now()
    return wake_h() <= t.hour < sleep_h()


def next_wake(t=None):
    t = t or now()
    w = t.replace(hour=wake_h(), minute=0, second=0, microsecond=0)
    return w if t < w else w + timedelta(days=1)


def today_sleep(t=None):
    t = t or now()
    if sleep_h() >= 24:
        return (t + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return t.replace(hour=sleep_h(), minute=0, second=0, microsecond=0)


def day_key(t=None):
    """The resident's 'day': the night after SLEEP_H still belongs to the day that just ended."""
    t = t or now()
    return (t - timedelta(days=1) if t.hour < wake_h() else t).strftime("%Y-%m-%d")


def human_date(t):
    return f"{WEEKDAYS[t.weekday()]}, {t.day} {MONTHS[t.month - 1]}, {t:%H:%M}"


def hhmm(ts):
    return datetime.fromtimestamp(ts, TZ).strftime("%H:%M")
