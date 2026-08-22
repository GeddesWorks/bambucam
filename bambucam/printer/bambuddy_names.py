from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

logger = logging.getLogger("bambucam")


def _http_get_json(url: str, api_key: str, timeout: float):
    request = urllib.request.Request(url)
    if api_key:
        request.add_header("X-API-Key", api_key)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def _records(payload) -> list[dict]:
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for key in ("items", "results", "archives", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [r for r in value if isinstance(r, dict)]
    return []


def _record_time(record: dict) -> datetime | None:
    for key in ("created_at", "last_run_at", "completed_at"):
        raw = record.get(key)
        if not isinstance(raw, str) or not raw:
            continue
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        # Bambuddy writes these without an offset; they are UTC.
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def fetch_print_name(base_url: str, api_key: str, job_name: str,
                     started_at: datetime | None = None,
                     timeout: float = 8.0, limit: int = 20,
                     fetch: Callable | None = None) -> str | None:
    """The model's real name for a print, or None.

    Bambu Studio names a project after its slicer settings unless you rename
    it, so the filename is usually something like "0.2mm layer, 2 walls, 15%
    infill". Bambuddy's archive record carries the actual model name in
    `print_name` (e.g. "Fidget Slider"), which makes a far better video name.

    Bambu Studio reuses that settings-derived filename across completely
    different models, so several archive records commonly share it. Pass
    *started_at* to pick the record closest in time to this print; without it
    the newest match wins, which is right for a print happening now and wrong
    for anything retroactive.

    Never raises: a naming nicety must not fail an upload, so every problem
    returns None and the caller falls back to the job slug.
    """
    if not base_url or not job_name:
        return None

    getter = fetch or _http_get_json
    url = f"{base_url.rstrip('/')}/api/v1/archives/?limit={int(limit)}"
    try:
        records = _records(getter(url, api_key, timeout))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as e:
        logger.warning("Could not look up print name: %s", e,
                       extra={"event": "PRINT_NAME_LOOKUP_FAILED"})
        return None

    from bambucam.models import slugify_job_name

    wanted = job_name.strip().lower()
    wanted_slug = slugify_job_name(job_name).lower()
    matches = []
    for record in records:
        filename = str(record.get("filename") or "")
        stem = filename.rsplit(".", 1)[0].strip()
        # Compare slugs as well as raw text: punctuation survives differently
        # on either side ("15% infill" vs "15-infill"), so exact matching alone
        # misses records that are plainly the same print.
        if (stem.lower() != wanted
                and filename.strip().lower() != wanted
                and slugify_job_name(stem).lower() != wanted_slug):
            continue
        name = record.get("print_name")
        if isinstance(name, str) and name.strip():
            matches.append((record, name.strip()))

    if not matches:
        logger.debug("No archive record matched job %r", job_name,
                     extra={"event": "PRINT_NAME_NOT_FOUND"})
        return None

    if started_at is not None and len(matches) > 1:
        reference = started_at if started_at.tzinfo else started_at.replace(
            tzinfo=timezone.utc)
        dated = [(r, n) for r, n in matches if _record_time(r) is not None]
        if dated:
            record, name = min(
                dated, key=lambda rn: abs(_record_time(rn[0]) - reference))
            return name

    return matches[0][1]
