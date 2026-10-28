"""Client for the Meta Model API. Money in USD, waits in seconds."""

import os
import random
import time
from dataclasses import dataclass
from typing import Any, Callable

import requests

from autosolar.ledger import PRICES, Ledger, UnknownModel

DEFAULT_MODEL = "muse-spark-1.3-contributor"

STANDARD_SPARK_MODELS = frozenset({"muse-spark-1.3", "muse-spark-1.2", "muse-spark-1.1"})

_BASE_URL = "https://api.meta.ai/v1"

_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})

_RATE_LIMIT_HEADERS = (
    "x-ratelimit-limit-requests",
    "x-ratelimit-remaining-requests",
    "x-ratelimit-limit-tokens",
    "x-ratelimit-remaining-tokens",
)

_MAX_BODY_CHARS = 500


class MetaAPIError(RuntimeError):
    """Raised for Meta API failures. Never holds the API key."""


@dataclass
class Result:
    """One parsed response. Money in USD, searches in queries."""

    text: str
    citations: list[dict]
    web_searches: int
    usage: dict
    cost_usd: float
    response_id: str | None
    model: str
    rate_limit: dict[str, str]
    raw: dict


def _body_text(resp: Any) -> str:
    """Best text view of a response body."""
    text = getattr(resp, "text", "")
    if text is None:
        return ""
    return str(text)


def _scrub(text_str: str, api_key: str) -> str:
    """Hide the key in one string. Input in str, output in str."""
    if api_key:
        return text_str.replace(api_key, "<key>")
    return text_str


def _failure_message(status_code: Any, body_text: str, api_key: str) -> str:
    """Error text with status and up to 500 body chars, key hidden."""
    return (
        "Meta API error "
        + str(status_code)
        + ": "
        + _scrub(body_text, api_key)[:_MAX_BODY_CHARS]
    )


def _count_searches(data: dict[str, Any]) -> int:
    """Count web search call items. Count in queries."""
    total_int = 0
    for item in data.get("output") or []:
        if isinstance(item, dict) and item.get("type") == "web_search_call":
            total_int += 1
    return total_int


def _token_usage(data: dict[str, Any], searches_int: int) -> dict[str, Any]:
    """Counts passed to the ledger. Tokens in tokens, searches in queries."""
    usage_raw = data.get("usage")
    if not isinstance(usage_raw, dict):
        raise MetaAPIError("Meta API response has no usage to cost")
    input_detail = usage_raw.get("input_tokens_details") or {}
    output_detail = usage_raw.get("output_tokens_details") or {}
    if not isinstance(input_detail, dict):
        input_detail = {}
    if not isinstance(output_detail, dict):
        output_detail = {}
    return {
        "input_tokens": usage_raw.get("input_tokens") or 0,
        "cached_tokens": input_detail.get("cached_tokens") or 0,
        "output_tokens": usage_raw.get("output_tokens") or 0,
        "reasoning_tokens": output_detail.get("reasoning_tokens") or 0,
        "search_queries": searches_int,
    }


def _parse_text(data: dict[str, Any]) -> tuple[str, list[dict]]:
    """Join output text parts and collect url citations."""
    parts: list[str] = []
    cites: list[dict] = []
    for item in data.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if not isinstance(part, dict) or part.get("type") != "output_text":
                continue
            parts.append(str(part.get("text") or ""))
            for ann in part.get("annotations") or []:
                if not isinstance(ann, dict):
                    continue
                if ann.get("type") != "url_citation":
                    continue
                cites.append(
                    {
                        "url": ann.get("url"),
                        "title": ann.get("title"),
                        "start_index": ann.get("start_index"),
                        "end_index": ann.get("end_index"),
                    }
                )
    return "".join(parts), cites


def _rate_limit(headers: Any) -> dict[str, str]:
    """Keep the four rate limit headers that are present."""
    lowered: dict[str, Any] = {}
    if headers:
        for key, val in dict(headers).items():
            lowered[str(key).lower()] = val
    out: dict[str, str] = {}
    for name in _RATE_LIMIT_HEADERS:
        if name in lowered and lowered[name] is not None:
            out[name] = str(lowered[name])
    return out


class MetaClient:
    """Wrapper for paid Meta Model API calls. Money in USD."""

    def __init__(
        self,
        ledger: Ledger,
        *,
        api_key: str | None = None,
        base_url: str = _BASE_URL,
        post: Callable[..., Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_retries: int = 4,
        timeout_s: float = 300.0,
    ) -> None:
        """Store deps. Key in str, base URL in str, timeout in seconds."""
        key = api_key if api_key is not None else os.environ.get("MODEL_API_KEY")
        if not key:
            raise RuntimeError("MODEL_API_KEY is not set in the environment")
        self._ledger = ledger
        self._api_key = key
        self._base_url = base_url
        self._post = post if post is not None else requests.post
        self._sleep = sleep
        self._max_retries = max_retries
        self._timeout_s = timeout_s

    def respond(
        self,
        run_id: str,
        stage: str,
        input: Any,
        *,
        estimate_usd: float,
        model: str = DEFAULT_MODEL,
        live: bool = False,
        tools: Any | None = None,
        reasoning_effort: str | None = None,
        include: Any | None = None,
        metadata: Any | None = None,
        allow_standard: bool = False,
        images: int = 0,
        text_format: Any | None = None,
    ) -> Result:
        """One model call with cost checks. Money in USD, images in images."""
        if text_format is not None and (
            not isinstance(text_format, dict)
            or text_format.get("type") != "json_schema"
            or not isinstance(text_format.get("name"), str)
            or not isinstance(text_format.get("schema"), dict)
        ):
            raise ValueError("text_format must be a json_schema dict")
        if model in STANDARD_SPARK_MODELS and not allow_standard:
            raise ValueError("standard model needs allow_standard: " + str(model))
        if model not in PRICES:
            raise UnknownModel("unknown model: " + str(model))
        kind = PRICES[model].get("kind")
        if kind == "per_image":
            if images < 1:
                raise ValueError("per image model needs images >= 1")
        elif images != 0:
            raise ValueError("token model needs images == 0")
        self._ledger.check(run_id, estimate_usd, live=live)
        body: dict[str, Any] = {"model": model, "input": input}
        if tools is not None:
            body["tools"] = tools
        if reasoning_effort is not None:
            body["reasoning"] = {"effort": reasoning_effort}
        if include is not None:
            body["include"] = include
        if metadata is not None:
            body["metadata"] = metadata
        if text_format is not None:
            body["text"] = {"format": text_format}
        resp = self._send(body)
        data = self._read_body(resp)
        searches_int = _count_searches(data)
        usage: dict[str, Any]
        if kind == "per_image":
            usage = {"images": images}
            row = self._ledger.record(run_id, stage, model, live=live, images=images)
        else:
            usage = _token_usage(data, searches_int)
            row = self._ledger.record(run_id, stage, model, live=live, **usage)
        named = data.get("model")
        if named is not None and named != model:
            raise MetaAPIError(
                "model mismatch: requested " + str(model) + " got " + str(named)
            )
        text_str, cites = _parse_text(data)
        return Result(
            text=text_str,
            citations=cites,
            web_searches=searches_int,
            usage=usage,
            cost_usd=float(row["cost_usd"]),
            response_id=data.get("id"),
            model=named if isinstance(named, str) else model,
            rate_limit=_rate_limit(getattr(resp, "headers", None)),
            raw=data,
        )

    def _send(self, body: dict[str, Any]) -> Any:
        """POST with retry on 429, 5xx and drops. Waits in seconds."""
        url = self._base_url.rstrip("/") + "/responses"
        headers = {
            "Authorization": "Bearer " + self._api_key,
            "Content-Type": "application/json",
        }
        for attempt_int in range(self._max_retries + 1):
            try:
                resp = self._post(
                    url, headers=headers, json=body, timeout=self._timeout_s
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt_int >= self._max_retries:
                    raise MetaAPIError(
                        _scrub(str(exc), self._api_key)
                    ) from exc
                self._sleep(0.5 * (2**attempt_int) + random.uniform(0, 0.25))
                continue
            if resp.status_code == 200:
                return resp
            if resp.status_code in _RETRY_STATUS:
                if attempt_int >= self._max_retries:
                    raise MetaAPIError(
                        _failure_message(
                            resp.status_code, _body_text(resp), self._api_key
                        )
                    )
                self._sleep(0.5 * (2**attempt_int) + random.uniform(0, 0.25))
                continue
            raise MetaAPIError(
                _failure_message(resp.status_code, _body_text(resp), self._api_key)
            )
        raise MetaAPIError("Meta API gave up after retries")

    def _read_body(self, resp: Any) -> dict[str, Any]:
        """Parse the JSON body or raise MetaAPIError with key hidden."""
        try:
            data = resp.json()
        except Exception as exc:
            raise MetaAPIError(
                _failure_message(resp.status_code, _body_text(resp), self._api_key)
            ) from exc
        if not isinstance(data, dict):
            raise MetaAPIError(
                _failure_message(resp.status_code, _body_text(resp), self._api_key)
            )
        return data
