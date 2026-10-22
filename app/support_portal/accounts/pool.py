"""In-memory pre-seeded fake account pool. No real identity: user_id is
just a pool-assigned integer (spec section 3 — no PII)."""

import random
import threading
from dataclasses import dataclass, field

from support_portal.incidents.known_issues import SERVICES

TIERS = ["bronze", "silver", "gold"]

# Synthetic-generator tickets use user_ids in this range so they're
# trivially distinguishable from real attendee submissions.
SYNTHETIC_ID_START = 1000
SYNTHETIC_POOL_SIZE = 200


def is_synthetic_user_id(user_id: int) -> bool:
    return SYNTHETIC_ID_START <= user_id < SYNTHETIC_ID_START + SYNTHETIC_POOL_SIZE


@dataclass
class Account:
    user_id: int
    tier: str
    ticket_history: list[dict] = field(default_factory=list)


def _seed_history() -> list[dict]:
    n = random.randint(0, 3)
    return [{"service": random.choice(SERVICES)} for _ in range(n)]


class AccountPool:
    """Pool of real (check-in-assigned) accounts plus a fixed synthetic
    range, so get_account_context works for both live and generator
    tickets."""

    def __init__(self, size: int):
        self._lock = threading.Lock()
        self._size = size
        self._next_id = 1
        self._accounts: dict[int, Account] = {
            uid: Account(user_id=uid, tier=random.choice(TIERS), ticket_history=_seed_history())
            for uid in range(1, size + 1)
        }
        for uid in range(SYNTHETIC_ID_START, SYNTHETIC_ID_START + SYNTHETIC_POOL_SIZE):
            self._accounts[uid] = Account(user_id=uid, tier=random.choice(TIERS), ticket_history=_seed_history())

    def check_in(self) -> int | None:
        """Assigns the next unused real user_id, or None if the pool is exhausted."""
        with self._lock:
            if self._next_id > self._size:
                return None
            uid = self._next_id
            self._next_id += 1
            return uid

    def get(self, user_id: int) -> Account | None:
        return self._accounts.get(user_id)

    def record_ticket(self, user_id: int, service: str | None) -> None:
        if service is None:
            return
        account = self._accounts.get(user_id)
        if account is None:
            return
        with self._lock:
            account.ticket_history.insert(0, {"service": service})
            account.ticket_history = account.ticket_history[:5]
