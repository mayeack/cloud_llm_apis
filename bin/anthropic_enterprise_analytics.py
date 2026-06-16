#!/usr/bin/env python
"""Modular input: Claude Enterprise Analytics API.

Collects usage/cost, per-user usage/cost, and engagement/adoption endpoints
under /v1/organizations/analytics, exploding each into normalized ai.* events.
Respects the 31-day query window, 365-day historical lookback, and the 3-day
engagement data lag.
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
from lib_cloud_llm.httpclient import ApiError, HttpClient  # noqa: E402
from lib_cloud_llm.modinput_base import (  # noqa: E402
    BaseInput,
    as_bool,
    as_int,
    parse_csv,
)
from lib_cloud_llm.secrets import ensure_api_key, redact_email  # noqa: E402

SCHEME_NAME = "anthropic_enterprise_analytics"
INPUT_TYPE = "enterprise_analytics"

DEFAULT_BASE = "https://api.anthropic.com/v1/organizations/analytics"
MAX_WINDOW_SECS = 31 * 86400
DAY = 86400

ENGAGEMENT_KINDS = ("summaries", "users", "projects", "skills", "connectors")


class EnterpriseAnalyticsInput(BaseInput):
    def get_scheme(self):
        scheme = Scheme("Anthropic Enterprise Analytics")
        scheme.description = "Ingests the Claude Enterprise Analytics API."
        scheme.use_external_validation = True
        scheme.use_single_instance = False

        names = [
            ("api_key", True),
            ("base_url", False),
            ("index", False),
            ("interval", False),
            ("collect_usage_report", False),
            ("collect_cost_report", False),
            ("collect_user_usage_report", False),
            ("collect_user_cost_report", False),
            ("collect_engagement_users", False),
            ("collect_engagement_summaries", False),
            ("collect_engagement_projects", False),
            ("collect_engagement_skills", False),
            ("collect_engagement_connectors", False),
            ("bucket_width", False),
            ("initial_lookback_hours", False),
            ("usage_group_by", False),
            ("cost_group_by", False),
            ("products", False),
            ("models", False),
            ("user_ids", False),
            ("exclude_deleted_users", False),
            ("engagement_delay_days", False),
            ("engagement_initial_lookback_days", False),
            ("redact_actor_email", False),
            ("checkpoint_key", False),
            ("timeout", False),
            ("verify_ssl", False),
            ("proxy", False),
        ]
        for name, required in names:
            arg = Argument(name)
            arg.data_type = Argument.data_type_string
            arg.required_on_create = required
            arg.required_on_edit = False
            scheme.add_argument(arg)
        return scheme

    def validate_input(self, validation_definition):
        base_url = validation_definition.parameters.get("base_url") or DEFAULT_BASE
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
        base_url = conf.get("base_url") or DEFAULT_BASE
        bucket_width = conf.get("bucket_width") or "1h"
        lookback_hours = as_int(conf.get("initial_lookback_hours"), 24)
        timeout = as_int(conf.get("timeout"), 30)
        verify_ssl = as_bool(conf.get("verify_ssl"), True)
        proxy = conf.get("proxy") or None
        do_redact_email = as_bool(conf.get("redact_actor_email"), False)
        eng_delay_days = as_int(conf.get("engagement_delay_days"), 3)
        eng_lookback_days = as_int(conf.get("engagement_initial_lookback_days"), 7)
        ckpt_key = conf.get("checkpoint_key") or stanza_name
        redact_fn = redact_email if do_redact_email else None

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
        now = time.time()
        total = 0

        common_filters = {}
        for conf_key, param in (("products", "products[]"), ("models", "models[]"),
                                ("user_ids", "user_ids[]")):
            vals = parse_csv(conf.get(conf_key))
            if vals:
                common_filters[param] = vals

        if as_bool(conf.get("collect_usage_report"), True):
            total += self._collect_bucketed(
                ew, client, index, stanza_name, state, ckpt, now,
                report="usage", endpoint="/usage_report", sourcetype="anthropic:analytics:usage",
                bucket_width=bucket_width, lookback_secs=lookback_hours * 3600,
                group_by=parse_csv(conf.get("usage_group_by")
                                   or "product,model,context_window,inference_geo,speed"),
                filters=common_filters,
            )
        if as_bool(conf.get("collect_cost_report"), True):
            total += self._collect_bucketed(
                ew, client, index, stanza_name, state, ckpt, now,
                report="cost", endpoint="/cost_report", sourcetype="anthropic:analytics:cost",
                bucket_width="1d", lookback_secs=max(lookback_hours * 3600, DAY),
                group_by=parse_csv(conf.get("cost_group_by")
                                   or "product,model,cost_type,token_type,context_window,inference_geo,speed"),
                filters=common_filters,
            )
        if as_bool(conf.get("collect_user_usage_report"), True):
            total += self._collect_user(
                ew, client, index, stanza_name, now,
                endpoint="/user_usage_report", sourcetype="anthropic:analytics:user_usage",
                lookback_secs=lookback_hours * 3600, filters=common_filters,
                redact_fn=redact_fn, kind="usage",
            )
        if as_bool(conf.get("collect_user_cost_report"), True):
            total += self._collect_user(
                ew, client, index, stanza_name, now,
                endpoint="/user_cost_report", sourcetype="anthropic:analytics:user_cost",
                lookback_secs=max(lookback_hours * 3600, DAY), filters=common_filters,
                redact_fn=redact_fn, kind="cost",
            )

        for kind in ENGAGEMENT_KINDS:
            flag = "collect_engagement_%s" % kind
            default_on = kind != "users"  # users defaults off (higher sensitivity)
            if as_bool(conf.get(flag), default_on):
                total += self._collect_engagement(
                    ew, client, index, stanza_name, now, kind,
                    delay_days=eng_delay_days, lookback_days=eng_lookback_days,
                    redact_fn=redact_fn,
                )

        ckpt.write(state)
        self.emit_health(
            ew, index=index, stanza=stanza_name, input_type=INPUT_TYPE,
            status="success", http_status=200, events=total,
        )

    def _window(self, state, key, now, lookback_secs):
        prev_end = state.get(key)
        if prev_end:
            starting_at = prev_end
            start_epoch = _iso_to_epoch(prev_end) or (now - lookback_secs)
        else:
            start_epoch = now - lookback_secs
            starting_at = _epoch_to_iso(start_epoch)
        # Clamp to the API's 31-day maximum query window.
        if now - start_epoch > MAX_WINDOW_SECS:
            start_epoch = now - MAX_WINDOW_SECS
            starting_at = _epoch_to_iso(start_epoch)
        return starting_at, _epoch_to_iso(now)

    def _collect_bucketed(self, ew, client, index, stanza_name, state, ckpt, now,
                          *, report, endpoint, sourcetype, bucket_width,
                          lookback_secs, group_by, filters):
        start_key = "%s_starting_at" % report
        starting_at, ending_at = self._window(state, start_key, now, lookback_secs)
        params = {"starting_at": starting_at, "ending_at": ending_at,
                  "bucket_width": bucket_width}
        if group_by:
            params["group_by[]"] = group_by
        params.update(filters)

        count = 0
        latest_end = state.get(start_key)
        while True:
            resp = client.get(endpoint, params=params)
            org_id = resp.get("organization_id")
            refreshed = resp.get("data_refreshed_at")
            for bucket in resp.get("data") or []:
                results = bucket.get("results") or [bucket]
                for result in results:
                    if report == "usage":
                        ev = normalize.normalize_usage_row(
                            result, bucket, api_family="enterprise_analytics",
                            org_id=org_id, data_refreshed_at=refreshed)
                    else:
                        ev = normalize.normalize_cost_row(
                            result, bucket, api_family="enterprise_analytics",
                            org_id=org_id, data_refreshed_at=refreshed)
                    self.write_json_event(
                        ew, index=index, sourcetype=sourcetype,
                        source="anthropic:analytics:%s" % report, stanza=stanza_name,
                        payload=ev, event_time=_iso_to_epoch(bucket.get("starting_at")))
                    count += 1
                end = bucket.get("ending_at")
                if end and (latest_end is None or end > latest_end):
                    latest_end = end
            if resp.get("has_more") and resp.get("next_page"):
                params["page"] = resp["next_page"]
            else:
                break
        if latest_end:
            state[start_key] = latest_end
        return count

    def _collect_user(self, ew, client, index, stanza_name, now, *, endpoint,
                      sourcetype, lookback_secs, filters, redact_fn, kind):
        starting_at = _epoch_to_iso(now - lookback_secs)
        ending_at = _epoch_to_iso(now)
        params = {"starting_at": starting_at, "ending_at": ending_at}
        params.update(filters)
        count = 0
        while True:
            resp = client.get(endpoint, params=params)
            org_id = resp.get("organization_id")
            refreshed = resp.get("data_refreshed_at")
            for row in resp.get("data") or []:
                if kind == "usage":
                    ev = normalize.normalize_user_usage_row(
                        row, org_id=org_id, data_refreshed_at=refreshed,
                        redact_email_fn=redact_fn)
                else:
                    ev = normalize.normalize_user_cost_row(
                        row, org_id=org_id, data_refreshed_at=refreshed,
                        redact_email_fn=redact_fn)
                self.write_json_event(
                    ew, index=index, sourcetype=sourcetype,
                    source="anthropic:analytics:user_%s" % kind, stanza=stanza_name,
                    payload=ev, event_time=_iso_to_epoch(refreshed) or now)
                count += 1
            if resp.get("has_more") and resp.get("next_page"):
                params["page"] = resp["next_page"]
            else:
                break
        return count

    def _collect_engagement(self, ew, client, index, stanza_name, now, kind,
                            *, delay_days, lookback_days, redact_fn):
        end_epoch = now - delay_days * DAY
        start_epoch = end_epoch - lookback_days * DAY
        params = {
            "starting_at": _epoch_to_iso(start_epoch),
            "ending_at": _epoch_to_iso(end_epoch),
        }
        count = 0
        while True:
            resp = client.get("/%s" % kind, params=params)
            org_id = resp.get("organization_id")
            refreshed = resp.get("data_refreshed_at")
            for row in resp.get("data") or []:
                ev = normalize.normalize_engagement_row(
                    kind, row, org_id=org_id, data_refreshed_at=refreshed,
                    redact_email_fn=redact_fn)
                self.write_json_event(
                    ew, index=index, sourcetype="anthropic:analytics:engagement",
                    source="anthropic:analytics:%s" % kind, stanza=stanza_name,
                    payload=ev,
                    event_time=_iso_to_epoch(row.get("date") or row.get("starting_at"))
                    or end_epoch)
                count += 1
            if resp.get("has_more") and resp.get("next_page"):
                params["page"] = resp["next_page"]
            else:
                break
        return count


def _epoch_to_iso(epoch):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def _iso_to_epoch(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%d"):
        try:
            return calendar.timegm(time.strptime(value, fmt))
        except ValueError:
            continue
    return None


if __name__ == "__main__":
    sys.exit(EnterpriseAnalyticsInput().run(sys.argv))
