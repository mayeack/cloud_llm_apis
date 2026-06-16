"""Secret storage and PII redaction helpers.

API keys are never written to events or logs. They are persisted in Splunk's
encrypted storage/passwords store. The clear value supplied in inputs.conf is
moved into storage on first use and the stanza field is masked best-effort.
"""

from __future__ import annotations

import hashlib

MASK = "********"
REALM = "TA-cloud_llm_apis"


def _find(service, realm, username):
    for item in service.storage_passwords:
        if item.realm == realm and item.username == username:
            return item
    return None


def read_secret(service, username, realm=REALM):
    item = _find(service, realm, username)
    return item.clear_password if item else None


def store_secret(service, username, value, realm=REALM):
    existing = _find(service, realm, username)
    if existing is not None:
        existing.delete()
    service.storage_passwords.create(value, username, realm=realm)


def ensure_api_key(service, stanza, provided, mask_input_fn=None, realm=REALM):
    """Return the usable API key for a stanza.

    If `provided` is a real key (present and not the mask sentinel) it is stored
    encrypted, then the on-disk field is masked. Otherwise the previously stored
    secret is returned.
    """
    username = stanza
    if provided and provided != MASK:
        store_secret(service, username, provided, realm=realm)
        if mask_input_fn is not None:
            try:
                mask_input_fn(MASK)
            except Exception:
                # Masking is best-effort; never block ingestion on it.
                pass
        return provided
    stored = read_secret(service, username, realm=realm)
    return stored


def redact_email(email):
    if not email or "@" not in email:
        return email
    local, _, domain = email.partition("@")
    digest = hashlib.sha256(local.encode("utf-8")).hexdigest()[:12]
    return "%s@%s" % (digest, domain)


def redact_ip(ip):
    if not ip:
        return ip
    if ":" in ip:  # IPv6 - drop the lower half
        parts = ip.split(":")
        keep = parts[:4]
        return ":".join(keep) + "::/64"
    octets = ip.split(".")
    if len(octets) == 4:
        octets[-1] = "0"
        return ".".join(octets)
    return ip
