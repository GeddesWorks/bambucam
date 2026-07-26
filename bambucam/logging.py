from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "event": getattr(record, "event", record.funcName),
            "job_id": getattr(record, "job_id", None),
            "message": record.getMessage(),
        }
        extra_keys = {"frame", "state", "old_state", "new_state", "duration",
                      "file_id", "error", "frame_count"}
        for key in extra_keys:
            value = getattr(record, key, None)
            if value is not None:
                entry[key] = value
        entry = {k: v for k, v in entry.items() if v is not None}
        return json.dumps(entry)


def setup_logging(level: str = "INFO", log_file: str | None = None,
                  fmt: str = "json") -> logging.Logger:
    logger = logging.getLogger("bambucam")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()

    if fmt == "json":
        formatter = JsonFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def log_event(logger: logging.Logger, event: str, message: str,
              level: str = "INFO", **kwargs) -> None:
    log_level = getattr(logging, level.upper(), logging.INFO)
    logger.log(log_level, message, extra={"event": event, **kwargs})
