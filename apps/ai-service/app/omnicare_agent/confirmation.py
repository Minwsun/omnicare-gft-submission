from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import settings


def create_confirmation_token(payload: dict[str, Any], ttl_minutes: int = 10) -> tuple[str, datetime]:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
    body = {**payload, "exp": int(expires_at.timestamp())}
    encoded = base64.urlsafe_b64encode(json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode()).rstrip(b"=")
    signature = hmac.new(settings.action_confirmation_secret.encode(), encoded, hashlib.sha256).digest()
    token = f"{encoded.decode()}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"
    return token, expires_at


def verify_confirmation_token(token: str) -> dict[str, Any]:
    encoded_text, signature_text = token.split(".", 1)
    encoded = encoded_text.encode()
    expected = hmac.new(settings.action_confirmation_secret.encode(), encoded, hashlib.sha256).digest()
    signature = base64.urlsafe_b64decode(signature_text + "=" * (-len(signature_text) % 4))
    canonical_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    if not hmac.compare_digest(signature_text, canonical_signature) or not hmac.compare_digest(expected, signature):
        raise ValueError("INVALID_CONFIRMATION_TOKEN")
    payload = json.loads(base64.urlsafe_b64decode(encoded_text + "=" * (-len(encoded_text) % 4)))
    if int(payload["exp"]) < int(datetime.now(timezone.utc).timestamp()):
        raise ValueError("CONFIRMATION_TOKEN_EXPIRED")
    return payload
