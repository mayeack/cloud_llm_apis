"""Shared base for the TA-cloud_llm_apis modular inputs.

Provides logging, a splunkd service connection from the input session key,
event/health emission helpers, and small parsing utilities so the three input
scripts stay focused on their endpoint-specific logic.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import time as _time

try:
    from urllib.parse import urlsplit
except ImportError:  # pragma: no cover
    from urlparse import urlsplit  # type: ignore

from splunklib import client
from splunklib.modularinput import Event, Script

from .secrets import MASK

HEALTH_SOURCETYPE = "cloud_llm_apis:health"
HEALTH_SOURCE = "cloud_llm_apis:ta"


def get_logger(name):
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    splunk_home = os.environ.get("SPLUNK_HOME", "/opt/splunk")
    log_dir = os.path.join(splunk_home, "var", "log", "splunk")
    try:
        os.makedirs(log_dir, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            os.path.join(log_dir, "ta_cloud_llm_apis.log"),
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
        )
    except OSError:
        handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logger.addHandler(handler)
    return logger


def connect_service(metadata):
    """Build a splunklib service from input metadata (session key + server uri)."""
    session_key = metadata.get("session_key")
    server_uri = metadata.get("server_uri") or "https://127.0.0.1:8089"
    parts = urlsplit(server_uri)
    host = parts.hostname or "127.0.0.1"
    port = parts.port or 8089
    scheme = parts.scheme or "https"
    return client.connect(
        host=host,
        port=port,
        scheme=scheme,
        token=session_key,
        owner="nobody",
        app="TA-cloud_llm_apis",
    )


def parse_csv(value):
    if not value:
        return []
    return [v.strip() for v in str(value).split(",") if v.strip()]


def as_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def as_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class BaseInput(Script):
    """Common modular-input plumbing shared by all Cloud LLM API inputs."""

    LOG_NAME = "ta_cloud_llm_apis"

    def _setup(self, inputs):
        self.logger = get_logger(self.LOG_NAME)
        self.metadata = inputs.metadata
        self.checkpoint_dir = inputs.metadata.get("checkpoint_dir", ".")
        self.service = connect_service(inputs.metadata)

    def short_name(self, stanza_name):
        return stanza_name.split("://", 1)[-1]

    def mask_input_field(self, scheme, name, field="api_key", value=MASK):
        """Best-effort: blank a clear-text secret field in inputs.conf."""
        try:
            item = self.service.inputs[name, scheme]
            item.update(**{field: value})
        except Exception as exc:  # noqa: BLE001 - never block ingestion
            self.logger.warning("could not mask %s for %s: %s", field, name, exc)

    def write_json_event(self, ew, *, index, sourcetype, source, stanza, payload,
                         event_time=None):
        event = Event()
        event.stanza = stanza
        event.index = index
        event.sourceType = sourcetype
        event.source = source
        if event_time is not None:
            event.time = "%.3f" % float(event_time)
        event.data = json.dumps(payload, separators=(",", ":"), default=str)
        ew.write_event(event)

    def emit_health(self, ew, *, index, stanza, input_type, status, http_status=None,
                    events=0, message=None, extra=None):
        payload = {
            "ts": _now_iso(),
            "ai.provider": "anthropic",
            "ai.api_family": "health",
            "input_name": self.short_name(stanza),
            "input_type": input_type,
            "status": status,
            "events": events,
        }
        if http_status is not None:
            payload["http_status"] = http_status
        if message:
            payload["message"] = message
        if extra:
            payload.update(extra)
        try:
            self.write_json_event(
                ew,
                index=index,
                sourcetype=HEALTH_SOURCETYPE,
                source=HEALTH_SOURCE,
                stanza=stanza,
                payload=payload,
                event_time=_time.time(),
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("failed to emit health event: %s", exc)


def _now_iso():
    return _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime())
