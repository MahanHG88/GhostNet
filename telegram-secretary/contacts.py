import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONTACTS_FILE = os.path.join(BASE_DIR, "contacts.json")


def _all():
    try:
        with open(CONTACTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def get(chat_id):
    """The person behind a chat id, if she has named them. None means a stranger."""
    contact = _all().get(str(chat_id))
    return contact if isinstance(contact, dict) and contact.get("name") else None


def ids():
    return set(_all().keys())
