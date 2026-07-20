"""Compliance directory sync input handler."""

from __future__ import annotations

import time
from typing import Any, Dict, Tuple

from solnlib import log
from splunklib import modularinput as smi

from ta_anthropic_claude_enterprise.account import build_client_from_account, get_account_config
from ta_anthropic_claude_enterprise.api.client import AnthropicAPIError
from ta_anthropic_claude_enterprise.api.compliance import ComplianceAPI
from ta_anthropic_claude_enterprise.checkpoint import CheckpointStore
from ta_anthropic_claude_enterprise.constants import (
    SOURCETYPE_COMPLIANCE_GROUP,
    SOURCETYPE_COMPLIANCE_ORGANIZATION,
    SOURCETYPE_COMPLIANCE_USER,
)
from ta_anthropic_claude_enterprise.events import wrap_directory_record
from ta_anthropic_claude_enterprise.input_utils import (
    configure_logger,
    logger_for_input,
    write_json_event,
)


def validate_input(definition: smi.ValidationDefinition) -> None:
    return


def stream_events(inputs: smi.InputDefinition, event_writer: smi.EventWriter) -> None:
    for input_name, input_item in inputs.inputs.items():
        normalized_input_name = input_name.split("/")[-1]
        logger = logger_for_input(normalized_input_name)
        session_key = inputs.metadata["session_key"]
        configure_logger(logger, session_key)
        log.modular_input_start(logger, normalized_input_name)

        try:
            counts = _collect_directory(
                logger=logger,
                session_key=session_key,
                input_key=input_name,
                input_item=input_item,
                event_writer=event_writer,
            )
            total = sum(counts.values())
            for sourcetype, count in counts.items():
                log.events_ingested(
                    logger,
                    input_name,
                    sourcetype,
                    count,
                    input_item.get("index"),
                    account=input_item.get("account"),
                )
            logger.info("Directory sync complete: %s total records", total)
            log.modular_input_end(logger, normalized_input_name)
        except Exception as exc:
            log.log_exception(
                logger,
                exc,
                "compliance_directory_error",
                msg_before="Failed to sync compliance directory: ",
            )


def _collect_directory(
    logger,
    session_key: str,
    input_key: str,
    input_item: Dict[str, Any],
    event_writer: smi.EventWriter,
) -> Dict[str, int]:
    account_name = input_item.get("account")
    account = get_account_config(session_key, account_name)
    if account.get("compliance_key_type") == "admin_activities_only":
        raise ValueError(
            "Directory sync requires a Compliance Access Key (compliance_full), not an Admin API key"
        )

    client = build_client_from_account(session_key, account_name)
    compliance = ComplianceAPI(client)
    index = input_item.get("index")
    source_prefix = f"anthropic:compliance:directory:{account_name}"
    counts = {
        SOURCETYPE_COMPLIANCE_USER: 0,
        SOURCETYPE_COMPLIANCE_ORGANIZATION: 0,
        SOURCETYPE_COMPLIANCE_GROUP: 0,
    }

    # Users are organization-scoped in the Compliance API; iter_all_users
    # walks /v1/compliance/organizations -> /organizations/{uuid}/users.
    sync_handlers: Tuple[Tuple[str, str, Any], ...] = (
        ("organizations", SOURCETYPE_COMPLIANCE_ORGANIZATION, compliance.list_organizations),
        ("users", SOURCETYPE_COMPLIANCE_USER, compliance.iter_all_users),
        ("groups", SOURCETYPE_COMPLIANCE_GROUP, compliance.list_groups),
    )

    for resource_name, sourcetype, iterator in sync_handlers:
        try:
            for record in iterator():
                payload = wrap_directory_record(record, resource_name.rstrip("s"))
                write_json_event(
                    event_writer=event_writer,
                    payload=payload,
                    index=index,
                    sourcetype=sourcetype,
                    source=f"{source_prefix}:{resource_name}",
                )
                counts[sourcetype] += 1
        except AnthropicAPIError as exc:
            if exc.status_code == 403:
                logger.warning(
                    "Skipping %s sync: insufficient Compliance API scope (%s)",
                    resource_name,
                    exc,
                )
            else:
                raise

    CheckpointStore(session_key).set(input_key, {"last_sync_epoch": int(time.time())})
    return counts
