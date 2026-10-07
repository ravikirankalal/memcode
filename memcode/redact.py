"""Secret redaction. Stdlib only. `redact(text)` masks likely secrets with [REDACTED]."""
from __future__ import annotations

import re

MASK = "[REDACTED]"

_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----|\Z)",
    re.S)
_URL_CREDS = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^\s/@]+@")
_BEARER = re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=\-]{8,}")
_KEY_VALUE = re.compile(
    r"""(?ix)\b([A-Za-z0-9_.\-]*(?:SECRET|TOKEN|PASSWORD|PASSWD|KEY)[A-Za-z0-9_.\-]*)
        (\s*=\s*)("[^"]*"|'[^']*'|[^\s"'&;]+)""")
_TOKENS = re.compile(
    r"\b(?:A(?:KIA|SIA)[0-9A-Z]{16}"
    r"|gh[pousr]_[A-Za-z0-9]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|xox[abprs]-[A-Za-z0-9\-]{10,}"
    r"|sk-[A-Za-z0-9_\-]{16,})")


def _kv(m: re.Match) -> str:
    return f"{m.group(1)}{m.group(2)}{MASK}"


def redact(text: str) -> str:
    if not text:
        return text
    text = _PRIVATE_KEY.sub(MASK, text)
    text = _URL_CREDS.sub(lambda m: m.group(1) + MASK + "@", text)
    text = _BEARER.sub(lambda m: m.group(1) + MASK, text)
    text = _KEY_VALUE.sub(_kv, text)
    text = _TOKENS.sub(MASK, text)
    return text
