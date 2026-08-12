"""Polite HTTP client shared by every fetcher in the pipeline.

Three non-negotiables, carried over from the prior scraper:
  1. Identifying User-Agent (Wikidata and Overpass both block anonymous bulk traffic).
  2. Enforced minimum interval between requests, per host.
  3. Every response body written to raw/ and every request appended to a JSONL log,
     so any row in the output can be traced back to the bytes it came from.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests

PIPELINE_ROOT = Path(__file__).resolve().parent.parent
RAW_ROOT = PIPELINE_ROOT / "raw"
REQUEST_LOG = PIPELINE_ROOT / "output" / "request_log.jsonl"

USER_AGENT = (
    "ServiceNetZero-SNZConsole/0.1 "
    "(research: institutional food service contract history; "
    "contact: kiki@servicenetzero.org)"
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PoliteSession:
    """A requests.Session with a per-host floor on request spacing."""

    name: str
    min_interval_s: float = 1.0
    timeout_s: int = 120
    max_retries: int = 4

    def __post_init__(self) -> None:
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self._last_request_at = 0.0
        self.raw_dir = RAW_ROOT / self.name
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        REQUEST_LOG.parent.mkdir(parents=True, exist_ok=True)

    def _wait(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.min_interval_s:
            time.sleep(self.min_interval_s - elapsed)
        self._last_request_at = time.monotonic()

    @staticmethod
    def _payload_hash(payload: Any) -> str:
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:12]

    def cache_path_for(self, payload: Any, label: str = "") -> Path:
        """Where this exact request's response body lives. Public so a test can seed the
        cache and drive the real code path without a network call, rather than re-deriving
        the hash and drifting from it."""
        return self.raw_dir / f"{label or 'req'}_{self._payload_hash(payload)}.txt"

    def _log(self, record: dict) -> None:
        with REQUEST_LOG.open("a") as fh:
            fh.write(json.dumps(record) + "\n")

    def post_json(
        self,
        url: str,
        *,
        payload: dict,
        headers: dict | None = None,
        label: str = "",
        validate: Callable[[str], None] | None = None,
        use_cache: bool = True,
    ) -> str:
        """`post` with a JSON body instead of a form body.

        Same retry, backoff, request log and payload-hash cache — the three non-negotiables
        at the top of this file apply to a model API exactly as they do to Overpass. The
        cache is what makes a 500-article extraction resumable: the hash covers the whole
        request, so an interrupted run re-reads the calls it already paid for and only
        spends on the ones it has not made. Change the prompt and every hash changes, which
        is the correct behaviour — a cached answer to a different question is not an answer.

        `headers` may carry credentials, so it is deliberately never logged; only the URL,
        the status and the payload hash are.
        """
        return self._send(
            url, data=json.dumps(payload), payload_for_hash=payload,
            headers={"Content-Type": "application/json", **(headers or {})},
            label=label, validate=validate, use_cache=use_cache,
        )

    def post(
        self,
        url: str,
        *,
        data: dict,
        headers: dict | None = None,
        label: str = "",
        validate: Callable[[str], None] | None = None,
        use_cache: bool = True,
    ) -> str:
        """POST with retry/backoff. Returns the response body; saves it to raw/.

        `validate` is called on the body before it is accepted. WDQS will occasionally
        return HTTP 200 with a truncated body — without a parse check that surfaces as a
        crash 25 minutes into a run, so a validation failure is treated as retryable.

        Cached on the payload hash. These queries are expensive and idempotent, and a
        long fetch should not restart from zero because one chunk came back short.
        """
        return self._send(url, data=data, payload_for_hash=data, headers=headers,
                          label=label, validate=validate, use_cache=use_cache)

    def _send(
        self,
        url: str,
        *,
        data: Any,
        payload_for_hash: Any,
        headers: dict | None = None,
        label: str = "",
        validate: Callable[[str], None] | None = None,
        use_cache: bool = True,
    ) -> str:
        """The retry/cache/log loop shared by `post` and `post_json`.

        `data` is handed to requests as-is (a dict form-encodes, a string is sent verbatim);
        `payload_for_hash` is the structured form of the same request and is what the cache
        key and the log are built from, so a JSON body hashes by its content rather than by
        the accident of key order in the serialized string.
        """
        payload_hash = self._payload_hash(payload_for_hash)
        cache_path = self.cache_path_for(payload_for_hash, label)

        if use_cache and cache_path.exists():
            cached = cache_path.read_text()
            try:
                if validate:
                    validate(cached)
                return cached
            except Exception:
                cache_path.unlink()  # corrupt cache entry; refetch

        last_error = None
        for attempt in range(1, self.max_retries + 1):
            self._wait()
            started = _utcnow()
            try:
                resp = self.session.post(
                    url, data=data, headers=headers or {}, timeout=self.timeout_s
                )
            except requests.RequestException as exc:
                last_error = str(exc)
                self._log(
                    {
                        "ts": started,
                        "source": self.name,
                        "url": url,
                        "label": label,
                        "attempt": attempt,
                        "status": "exception",
                        "error": last_error,
                    }
                )
                time.sleep(min(2**attempt, 60))
                continue

            self._log(
                {
                    "ts": started,
                    "source": self.name,
                    "url": url,
                    "label": label,
                    "attempt": attempt,
                    "status": resp.status_code,
                    "bytes": len(resp.content),
                    "payload_hash": payload_hash,
                }
            )

            # 429/503 are the normal backpressure signals from both WDQS and Overpass.
            if resp.status_code in (429, 500, 502, 503, 504):
                retry_after = resp.headers.get("Retry-After")
                delay = int(retry_after) if retry_after and retry_after.isdigit() else min(2**attempt * 5, 120)
                last_error = f"HTTP {resp.status_code}"
                time.sleep(delay)
                continue

            resp.raise_for_status()

            if validate:
                try:
                    validate(resp.text)
                except Exception as exc:  # noqa: BLE001 - any parse failure is retryable
                    last_error = f"invalid body ({exc})"
                    self._log(
                        {
                            "ts": started,
                            "source": self.name,
                            "url": url,
                            "label": label,
                            "attempt": attempt,
                            "status": "invalid_body",
                            "bytes": len(resp.content),
                            "error": str(exc)[:200],
                        }
                    )
                    time.sleep(min(2**attempt * 3, 60))
                    continue

            cache_path.write_text(resp.text)
            return resp.text

        raise RuntimeError(f"{self.name}: {label} failed after {self.max_retries} attempts: {last_error}")
