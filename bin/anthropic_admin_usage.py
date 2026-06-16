#!/usr/bin/env python
"""Modular input: Claude Console Usage and Cost Admin API.

Collects GET /v1/organizations/usage_report/messages and
GET /v1/organizations/cost_report using an Admin API key. Nested bucket
results are exploded into one normalized ai.* event per row.
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
from lib_cloud_llm.secrets import ensure_api_key  # noqa: E402

SCHEME_NAME = "anthropic_admin_usage"
INPUT_TYPE = "admin_usage"

USAGE_ENDPOINT = "/v1/organizations/usage_report/messages"
COST_ENDPOINT = "/v1/organizations/cost_report"

FILTER_PARAMS = {
    "models": "models[]",
    "workspace_ids": "workspace_ids[]",
    "api_key_ids": "api_key_ids[]",
    "service_tiers": "service_tiers[]",
    "context_windows": "context_windows[]",
    "inference_geos": "inference_geos[]",
    "speeds": "speeds[]",
}


class AdminUsageInput(BaseInput):
    def get_scheme(self):
        scheme = Scheme("Anthropic Admin Usage and Cost")
        scheme.description = "Ingests the Claude Console Usage and Cost Admin API."
        scheme.use_external_validation = True
        scheme.use_single_instance = False

        names = [
            ("api_key", True),
            ("base_url", False),
            ("anthropic_version", False),
            ("index", False),
            ("interval", False),
            ("bucket_width", False),
            ("initial_lookback_minutes", False),
            ("group_by_usage", False),
            ("group_by_cost", False),
            ("models", False),
            ("workspace_ids", False),
            ("api_key_ids", False),
            ("service_tiers", False),
            ("context_windows", False),
            ("inference_geos", False),
            ("speeds", False),
            ("collect_usage", False),
            ("collect_cost", False),
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
        base_url = validation_definition.parameters.get("base_url") or "https://api.anthropic.com"
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
        version = conf.get("anthropic_version") or "2023-06-01"
        bucket_width = conf.get("bucket_width") or "1m"
        lookback_min = as_int(conf.get("initial_lookback_minutes"), 60)
        timeout = as_int(conf.get("timeout"), 30)
        verify_ssl = as_bool(conf.get("verify_ssl"), True)
        proxy = conf.get("proxy") or None
        collect_usage = as_bool(conf.get("collect_usage"), True)
        collect_cost = as_bool(conf.get("collect_cost"), True)
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
            extra_headers={"anthropic-version": version},
            timeout=timeout,
            verify_ssl=verify_ssl,
            proxy=proxy,
            logger=self.logger,
        )

        filters = {}
        for conf_key, param in FILTER_PARAMS.items():
            vals = parse_csv(conf.get(conf_key))
            if vals:
                filters[param] = vals

        total = 0
        ckpt = Checkpoint(self.checkpoint_dir, ckpt_key)
        state = ckpt.read()
        now = time.time()

        if collect_usage:
            total += self._collect_report(
                ew, client, index, stanza_name, state, now, ckpt,
                report="usage",
                endpoint=USAGE_ENDPOINT,
                bucket_width=bucket_width,
                lookback_min=lookback_min,
                group_by=parse_csv(conf.get("group_by_usage")
                                   or "model,workspace_id,api_key_id,service_tier,context_window,inference_geo"),
                filters=filters,
                sourcetype="anthropic:analytics:usage",
            )
        if collect_cost:
            total += self._collect_report(
                ew, client, index, stanza_name, state, now, ckpt,
                report="cost",
                endpoint=COST_ENDPOINT,
                bucket_width="1d",
                lookback_min=max(lookback_min, 1440),
                group_by=parse_csv(conf.get("group_by_cost") or "workspace_id,description"),
                filters={},
                sourcetype="anthropic:analytics:cost",
            )

        ckpt.write(state)
        self.emit_health(
            ew, index=index, stanza=stanza_name, input_type=INPUT_TYPE,
            status="success", http_status=200, events=total,
        )

    def _collect_report(self, ew, client, index, stanza_name, state, now, ckpt,
                        *, report, endpoint, bucket_width, lookback_min, group_by,
                        filters, sourcetype):
        start_key = "%s_starting_at" % report
        prev_end = state.get(start_key)
        if prev_end:
            starting_at = prev_end
        else:
            starting_at = _epoch_to_iso(now - lookback_min * 60)
        ending_at = _epoch_to_iso(now)

        params = {
            "starting_at": starting_at,
            "ending_at": ending_at,
            "bucket_width": bucket_width,
        }
        if group_by:
            params["group_by[]"] = group_by
        params.update(filters)

        count = 0
        latest_end = prev_end
        while True:
            resp = client.get(endpoint, params=params)
            for bucket in resp.get("data") or []:
                results = bucket.get("results") or []
                if not results:
                    results = [bucket]  # ungrouped: bucket carries the metrics
                for result in results:
                    if report == "usage":
                        ev = normalize.normalize_usage_row(
                            result, bucket, api_family="admin_usage")
                    else:
                        ev = normalize.normalize_cost_row(
                            result, bucket, api_family="admin_usage")
                    self.write_json_event(
                        ew, index=index, sourcetype=sourcetype,
                        source="anthropic:admin:%s" % report, stanza=stanza_name,
                        payload=ev, event_time=_iso_to_epoch(bucket.get("starting_at")),
                    )
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
    sys.exit(AdminUsageInput().run(sys.argv))
