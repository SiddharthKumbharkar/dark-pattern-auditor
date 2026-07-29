"""Structured logging shared by every command when invoked through dpa.py
(the unified entry point): JSON Lines to a log file (one object per
line -- timestamp, level, logger, message, plus any structured extra
fields), human-readable text to stdout. Each individual command's own
print()-based "OK ..."/"FAIL: ..." output is unchanged and remains the
primary result a human reads; this is an additional, thin band of
lifecycle events (command started/finished/crashed) giving a durable,
greppable audit trail of what ran, when, with what arguments, and how it
ended -- the command-invocation-level analogue of what run_manifest.json
already gives a single recorded episode.
"""

import json
import logging
import os
import sys
from typing import Any, Dict, Optional

from config.settings import resolve_path

DEFAULT_LOG_FILE = "logs/dpa.jsonl"
LOGGER_NAME = "dpa"


class JSONLFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extra_fields = getattr(record, "extra_fields", None)
        if extra_fields:
            payload.update(extra_fields)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload)


class HumanFormatter(logging.Formatter):
    def __init__(self):
        super().__init__("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")


def log_extra(**fields) -> Dict[str, Dict[str, Any]]:
    """Usage: logger.info("...", extra=log_extra(command=name, exit_code=0))"""
    return {"extra_fields": fields}


def configure_logging(log_file: Optional[str] = None, level: int = logging.INFO) -> logging.Logger:
    """Idempotent: clears any handlers this module previously installed on
    the "dpa" logger rather than accumulating duplicates across repeated
    calls (e.g. in tests, or if a command process re-invokes this)."""
    resolved_log_file = log_file or resolve_path(DEFAULT_LOG_FILE)
    os.makedirs(os.path.dirname(resolved_log_file) or ".", exist_ok=True)

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    logger.handlers = []
    logger.propagate = False

    file_handler = logging.FileHandler(resolved_log_file, encoding="utf-8")
    file_handler.setFormatter(JSONLFormatter())
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(HumanFormatter())
    logger.addHandler(stream_handler)

    return logger


def get_logger() -> logging.Logger:
    """Returns the "dpa" logger without (re)configuring handlers -- for
    command modules that want to emit their own structured events when
    they happen to be running under dpa.py. Safe to call even if
    configure_logging() was never called (a logger with no handlers just
    propagates to Python's default, which is effectively a no-op here
    since propagate=False is only set by configure_logging())."""
    return logging.getLogger(LOGGER_NAME)
