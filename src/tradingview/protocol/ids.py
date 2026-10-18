from __future__ import annotations

import secrets

ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"


def create_session_id(prefix: str = "xs") -> str:
    """Creates a random session or request ID such as `cs_Ab12Cd34Ef56`."""
    raw = secrets.token_bytes(12)
    suffix = "".join(ALPHABET[b % len(ALPHABET)] for b in raw)
    return f"{prefix}_{suffix}"


createSessionId = create_session_id
gen_session_id = create_session_id
genSessionId = create_session_id
