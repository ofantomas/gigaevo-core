"""Per-request token logger for LiteLLM proxy.

Records `prompt_tokens` / `completion_tokens` / routed `api_base` / latency
for every successful request. Written as jsonl to
`tools/.litellm_requests.jsonl` with rotation at 50 MB × 3 backups.

The point is that vLLM's Prometheus histograms use hardcoded bucket edges
(`..., 10000, 20000, +Inf`) identical for every model, so the tail of every
distribution gets crammed into one bin — and CDF interpolation across
`+Inf` fabricates uniform mass we don't actually have. Raw per-request
records let the monitor build honest histograms at any resolution.

Wired from `tools/litellm.sh` via:
    litellm_settings:
      callbacks: litellm_token_logger.token_logger
and PYTHONPATH exported to include `tools/`.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from litellm.integrations.custom_logger import CustomLogger

_HERE = Path(__file__).resolve().parent
LOG_PATH = _HERE / ".litellm_requests.jsonl"
_MAX_BYTES = 50 * 1024 * 1024
_BACKUP_COUNT = 3

_file_logger = logging.getLogger("litellm_token_logger.file")
_file_logger.setLevel(logging.INFO)
_file_logger.propagate = False
if not _file_logger.handlers:
    _handler = RotatingFileHandler(
        LOG_PATH, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT
    )
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _file_logger.addHandler(_handler)


def _extract_usage(response_obj: Any) -> dict[str, int] | None:
    usage = getattr(response_obj, "usage", None)
    if usage is None and isinstance(response_obj, dict):
        usage = response_obj.get("usage")
    if usage is None:
        return None
    if hasattr(usage, "model_dump"):
        usage = usage.model_dump()
    elif hasattr(usage, "dict"):
        usage = usage.dict()
    if not isinstance(usage, dict):
        return None
    p = usage.get("prompt_tokens")
    c = usage.get("completion_tokens")
    if p is None or c is None:
        return None
    return {"prompt_tokens": int(p), "completion_tokens": int(c)}


class TokenLogger(CustomLogger):
    def _emit(
        self,
        kwargs: dict,
        response_obj: Any,
        start_time: datetime | None,
        end_time: datetime | None,
    ) -> None:
        try:
            usage = _extract_usage(response_obj)
            if usage is None:
                return
            lp = kwargs.get("litellm_params") or {}
            model = kwargs.get("model") or lp.get("model")
            api_base = lp.get("api_base")
            lat_s = None
            if start_time is not None and end_time is not None:
                lat_s = round((end_time - start_time).total_seconds(), 3)
            rec = {
                "ts": datetime.now(UTC).isoformat(timespec="seconds"),
                "model": model,
                "api_base": api_base,
                "prompt_tokens": usage["prompt_tokens"],
                "completion_tokens": usage["completion_tokens"],
                "latency_s": lat_s,
            }
            _file_logger.info(json.dumps(rec, separators=(",", ":")))
        except Exception:
            # Never break the proxy because of logging.
            pass

    def log_success_event(self, kwargs, response_obj, start_time, end_time):
        self._emit(kwargs, response_obj, start_time, end_time)

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        self._emit(kwargs, response_obj, start_time, end_time)


token_logger = TokenLogger()
