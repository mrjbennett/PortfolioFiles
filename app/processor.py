"""A stand-in for the third-party payment processor.

State lives in memory and is deliberately separate from the app database, so a test can
compare what the processor captured with what the app recorded.

Test cards:
  4242 4242 4242 4242  captured
  4000 0000 0000 0002  declined (insufficient_funds)
Any card with an expiry in the past is rejected as expired_card.
"""

import threading
import uuid
from datetime import datetime, timezone

_lock = threading.Lock()
_charges = []


class Declined(Exception):
    def __init__(self, code, reason):
        super().__init__(reason)
        self.code = code
        self.reason = reason


def _expired(exp: str) -> bool:
    month, year = int(exp[:2]), 2000 + int(exp[3:])
    today = datetime.now(timezone.utc)
    return (year, month) < (today.year, today.month)


def charge(number: str, exp: str, amount: int, reference: str) -> dict:
    if _expired(exp):
        raise Declined("expired_card", "expired_card")
    if number == "4000000000000002":
        raise Declined("card_declined", "insufficient_funds")
    record = {
        "id": "ch_" + uuid.uuid4().hex[:12],
        "reference": reference,
        "amount": amount,
        "status": "captured",
    }
    with _lock:
        _charges.append(record)
    return record


def charges(reference=None):
    with _lock:
        return [c for c in _charges if reference in (None, c["reference"])]


def reset():
    with _lock:
        _charges.clear()
