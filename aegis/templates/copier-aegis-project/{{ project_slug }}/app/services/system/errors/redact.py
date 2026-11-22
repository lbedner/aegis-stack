"""Best-effort retained payload redaction, not a guarantee for arbitrary prose.

Structured credential keys are removed recursively; locals are never retained.
Free text masks named credentials, authorization schemes and URL userinfo.
Applications must still avoid logging secrets or personal data in arbitrary text.
"""

import json
import re

from app.core.credential import hide_passwords

# A key or an assignment naming one of these holds a credential.
KEYWORDS = r"password|passwd|secret|token|api[_-]?key|authorization|cookie|credential"
SECRET = re.compile(KEYWORDS, re.I)
# Names holding a secret the words above miss, each a whole part of a name
# (``otp`` and ``totp_seed``, never ``footprint``). Overseer hides a table's
# column by the same rule (``db_rows.masked``).
NAMED = re.compile(
    r"(?i)(?:^|_)(?:ciphertext|encrypted|private_key|signing_key|t?otp"
    r"|recovery_codes?|salt)(?:_|$)"
)
LOCALS = {"locals", "frame_locals", "local_vars"}
# An assignment to a name holding one of the words, or ending in ``_key``
# (``OPENAI_API_KEY=...``, ``"ENCRYPTION_KEY": "..."``), as an environment,
# a config or a command line says it.
ASSIGN = re.compile(
    rf"(?i)(\b\w*(?:{KEYWORDS})\w*|\b\w+_key\b)([\"' ]*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;\"]+)"
)
AUTH = re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+")
# A token by the prefix its maker gives it, wherever it stands.
TOKEN = re.compile(r"\b(?:sk-|ghp_|gho_|ghs_|github_pat_|xox[abp]-|AKIA)[\w-]{8,}")


def secret_name(name: str) -> bool:
    """Whether a key or column ``name`` holds a secret."""
    return bool(SECRET.search(name) or NAMED.search(name))


def text(value: str) -> str:
    value = AUTH.sub(r"\1 [redacted]", value)
    value = TOKEN.sub("[redacted]", value)
    value = ASSIGN.sub(r"\1\2[redacted]", value)
    return hide_passwords(value)


def clean(value: object) -> object:
    if isinstance(value, dict):
        return {
            str(k): "[redacted]" if secret_name(str(k)) else clean(v)
            for k, v in value.items()
            if str(k).lower() not in LOCALS
        }
    if isinstance(value, list):
        return [clean(v) for v in value]
    return text(value) if isinstance(value, str) else value


def fields(values: tuple[tuple[str, str], ...]) -> dict[str, str]:
    result = {}
    for key, value in values:
        if key.lower() in LOCALS:
            continue
        if secret_name(key):
            result[key] = "[redacted]"
            continue
        try:
            parsed = json.loads(value)
        except ValueError:
            result[key] = text(value)
        else:
            result[key] = json.dumps(clean(parsed))
    return result
