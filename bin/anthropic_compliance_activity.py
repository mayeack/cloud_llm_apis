#!/usr/bin/env python
"""Modular input: Anthropic Compliance API Activity Feed.

Cursor-driven incremental ingestion of GET /v1/compliance/activities. Each
Activity object is indexed raw (one event each) and normalized at search time
by props.conf. Actor PII can be redacted before indexing.
"""

from __future__ import annotations

import os
import sys

BIN_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BIN_DIR, "..", "lib"))
sys.path.insert(0, BIN_DIR)

import calendar  # noqa: E402
import time  # noqa: E402

from splunklib.modularinput import Argument, Scheme  # noqa: E402

from lib_cloud_llm import normalize  # noqa: E402
from lib_cloud_llm.checkpoint import Checkpoint  # noqa: E402
from lib_cloud_llm.httpclient import ApiError, CursorResetError, HttpClient  # noqa: E402
from lib_cloud_llm.modinput_base import (  # noqa: E402
    BaseInput,
    as_bool,
    as_int,
    parse_csv,
)
from lib_cloud_llm.secrets import ensure_api_key, redact_email, redact_ip  # noqa: E402

SCHEME_NAME = "anthropic_compliance_activity"
INPUT_TYPE = "compliance_activity"


class ComplianceActivityInput(BaseInput):
    def get_scheme(self):
        scheme = Scheme("Anthropic Compliance Activity Feed")
        scheme.description = "Ingests the Anthropic Compliance API Activity Feed."
        scheme.use_external_validation = True
        scheme.use_single_instance = False

        args = [
            ("api_key", True),
            ("base_url", False),
            ("endpoint", False),
            ("index", False),
            ("interval", False),
            ("limit", False),
            ("initial_lookback_minutes", False),
            ("activity_types", False),
            ("organization_ids", False),
            ("actor_ids", False),
            ("checkpoint_key", False),
            ("include_raw_content", False),
            ("redact_actor_email", False),
            ("redact_ip_address", False),
            ("timeout", False),
            ("verify_ssl", False),
            ("proxy", False),
        ]
        for name, required in args:
            arg = Argument(name)
            arg.data_type = Argument.data_type_string
            arg.required_on_create = required
            arg.required_on_edit = False
            scheme.add_argument(arg)
        return scheme

    def validate_input(self, validation_definition):
        params = validation_definition.parameters
        base_url = params.get("base_url") or "https://api.anthropic.com"
        if not base_url.lower().startswith("https://"):
            raise ValueError("base_url must use HTTPS")

    def stream_events(self, inputs, ew):
        self._setup(inputs)
        for stanza_name, conf in inputs.inputs.items():
            try:
                self._collect(stanza_name, conf, ew)
            except Exception as exc:  # noqa: BLE001
                self.logger.error("input %s failed: %s", stanza_name, exc)
                self.emit_health(
                    ew,
                    index=conf.get("index") or "cloud_llm_apis",
                    stanza=stanza_name,
                    input_type=INPUT_TYPE,
                    status="error",
                    message=str(exc),
                )

    def _collect(self, stanza_name, conf, ew):
        index = conf.get("index") or "cloud_llm_apis"
        base_url = conf.get("base_url") or "https://api.anthropic.com"
        endpoint = conf.get("endpoint") or "/v1/compliance/activities"
        sourcetype = "anthropic:compliance:activity"
        limit = min(as_int(conf.get("limit"), 5000), 5000)
        lookback_min = as_int(conf.get("initial_lookback_minutes"), 60)
        timeout = as_int(conf.get("timeout"), 30)
        verify_ssl = as_bool(conf.get("verify_ssl"), True)
        proxy = conf.get("proxy") or None
        do_redact_email = as_bool(conf.get("redact_actor_email"), False)
        do_redact_ip = as_bool(conf.get("redact_ip_address"), False)
        ckpt_key = conf.get("checkpoint_key") or stanza_name

        api_key = ensure_api_key(
            self.service,
            stanza_name,
            conf.get("api_key"),
            mask_input_fn=lambda v: self.mask_input_field(SCHEME_NAME, stanza_name, value=v),
        )
        if not api_key:
            raise ApiError("no API key available for %s" % stanza_name)

        client = HttpClient(
            api_key,
            base_url,
            extra_headers={"anthropic-version": "2023-06-01"},
            timeout=timeout,
            verify_ssl=verify_ssl,
            proxy=proxy,
            logger=self.logger,
        )

        ckpt = Checkpoint(self.checkpoint_dir, ckpt_key)
        state = ckpt.read()
        last_id = state.get("last_id")

        params = {"limit": limit}
        for key, conf_key in (
            ("activity_types[]", "activity_types"),
            ("organization_ids[]", "organization_ids"),
            ("actor_ids[]", "actor_ids"),
        ):
            vals = parse_csv(conf.get(conf_key))
            if vals:
                params[key] = vals

        if last_id:
            params["after_id"] = last_id
        else:
            gte = time.gmtime(time.time() - lookback_min * 60)
            params["created_at.gte"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", gte)

        total = 0
        newest_id = last_id
        http_status = 200
        try:
            while True:
                resp = client.get(endpoint, params=params)
                activities = resp.get("data") or []
                for activity in activities:
                    self._write_activity(
                        ew, index, sourcetype, stanza_name, activity,
                        do_redact_email, do_redact_ip,
                    )
                    total += 1
                    newest_id = activity.get("id") or newest_id
                if resp.get("has_more") and resp.get("last_id"):
                    params.pop("created_at.gte", None)
                    params["after_id"] = resp["last_id"]
                else:
                    break
        except CursorResetError:
            # Cursor no longer valid: drop checkpoint and fall back to lookback.
            self.logger.warning("cursor reset for %s; clearing checkpoint", stanza_name)
            ckpt.write({})
            raise

        if newest_id and newest_id != last_id:
            ckpt.write({"last_id": newest_id, "updated_at": time.time()})

        self.emit_health(
            ew,
            index=index,
            stanza=stanza_name,
            input_type=INPUT_TYPE,
            status="success",
            http_status=http_status,
            events=total,
            extra={"checkpoint_last_id": newest_id},
        )

    def _write_activity(self, ew, index, sourcetype, stanza_name, activity,
                        do_redact_email, do_redact_ip):
        if do_redact_email or do_redact_ip:
            normalize.redact_activity(
                activity,
                redact_email_fn=redact_email if do_redact_email else None,
                redact_ip_fn=redact_ip if do_redact_ip else None,
            )
        content, deletion = normalize.compliance_risk_flags(activity.get("type"))
        if content:
            activity["ai.risk.content_retrieved"] = True
        if deletion:
            activity["ai.risk.deletion_action"] = True

        event_time = _iso_to_epoch(activity.get("created_at"))
        self.write_json_event(
            ew,
            index=index,
            sourcetype=sourcetype,
            source="anthropic:compliance:activity",
            stanza=stanza_name,
            payload=activity,
            event_time=event_time,
        )


def _iso_to_epoch(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            return calendar.timegm(time.strptime(value, fmt))
        except ValueError:
            continue
    return None


if __name__ == "__main__":
    sys.exit(ComplianceActivityInput().run(sys.argv))
