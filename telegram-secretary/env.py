import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _read(path):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            # First non-empty value wins, so this project's .env beats a shared one - but an
            # empty placeholder here must not block a real value from the shared file.
            if value and not os.environ.get(key):
                os.environ[key] = value


def load():
    """This project's .env first, then any file listed in SHARED_ENV - so API keys can stay
    wherever they already live on the box instead of being copied around."""
    _read(os.path.join(BASE_DIR, ".env"))
    for path in os.environ.get("SHARED_ENV", "").split(","):
        path = path.strip()
        if path:
            _read(os.path.expanduser(path))


def get_int(name, default):
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default
