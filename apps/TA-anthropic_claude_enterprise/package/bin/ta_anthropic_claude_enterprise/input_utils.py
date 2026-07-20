"""Thin binding of ai_common.input_utils to this add-on's identity."""

from __future__ import annotations

import logging

from ai_common import input_utils as _shared

from ta_anthropic_claude_enterprise import ADDON_NAME

SETTINGS_CONF = "ta-anthropic_claude_enterprise_settings"

parse_event_time = _shared.parse_event_time
write_json_event = _shared.write_json_event
parse_int = _shared.parse_int
parse_bool = _shared.parse_bool


def logger_for_input(input_name: str) -> logging.Logger:
    return _shared.logger_for_input(ADDON_NAME, input_name)


def configure_logger(logger: logging.Logger, session_key: str) -> None:
    _shared.configure_logger(logger, session_key, ADDON_NAME, SETTINGS_CONF)
