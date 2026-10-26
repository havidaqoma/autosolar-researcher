"""Cost ledger for paid model calls. All money in USD, all audio in seconds."""

import datetime as dt
import json
import time
from pathlib import Path
from typing import Any, Callable


WEB_SEARCH_USD_PER_QUERY = 0.0025

PRICES: dict[str, dict] = {
    "muse-spark-1.3-contributor": {
        "kind": "tokens",
        "input_usd_per_mtok": 0.10,
        "cached_input_usd_per_mtok": 0.002,
        "output_usd_per_mtok": 0.20,
    },
    "muse-spark-1.2-contributor": {
        "kind": "tokens",
        "input_usd_per_mtok": 0.10,
        "cached_input_usd_per_mtok": 0.002,
        "output_usd_per_mtok": 0.20,
    },
    "muse-spark-1.3": {
        "kind": "tokens",
        "input_usd_per_mtok": 1.25,
        "cached_input_usd_per_mtok": 0.15,
        "output_usd_per_mtok": 4.25,
    },
    "muse-spark-1.2": {
        "kind": "tokens",
        "input_usd_per_mtok": 1.25,
        "cached_input_usd_per_mtok": 0.15,
        "output_usd_per_mtok": 4.25,
    },
    "muse-spark-1.1": {
        "kind": "tokens",
        "input_usd_per_mtok": 1.25,
        "cached_input_usd_per_mtok": 0.15,
        "output_usd_per_mtok": 4.25,
    },
    "muse-wonder-1.0": {
        "kind": "tokens",
        "input_usd_per_mtok": 4.00,
        "cached_input_usd_per_mtok": 0.20,
        "output_usd_per_mtok": 20.00,
    },
    "sam-3.1": {"kind": "per_image", "usd_per_image": 0.0025},
    "muse-image-1.0": {"kind": "per_image", "usd_per_image": 0.01},
    "muse-voice-transcribe-1.0": {"kind": "per_audio_s", "usd_per_s": 0.00005},
    "muse-glimmer-local": {"kind": "free"},
}

_TOL_USD = 1e-9

_ALLOWED_USAGE_KEYS = frozenset(
    {
        "input_tokens",
        "cached_tokens",
        "output_tokens",
        "reasoning_tokens",
        "images",
        "audio_s",
        "search_queries",
    }
)


class UnknownModel(ValueError):
    """Raised when a model id is not in PRICES."""


class BudgetExceeded(RuntimeError):
    """Raised when an estimate would push spending above a cap in USD."""


def call_cost_usd(
    model: str,
    *,
    input_tokens: float = 0,
    cached_tokens: float = 0,
    output_tokens: float = 0,
    reasoning_tokens: float = 0,
    images: float = 0,
    audio_s: float = 0,
    search_queries: float = 0,
) -> float:
    """Cost in USD of one call. Tokens in tokens, audio in seconds."""
    if model not in PRICES:
        raise UnknownModel("unknown model: " + str(model))
    counts = {
        "input_tokens": input_tokens,
        "cached_tokens": cached_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
        "images": images,
        "audio_s": audio_s,
        "search_queries": search_queries,
    }
    for key_name, count_val in counts.items():
        if count_val < 0:
            raise ValueError("negative count for " + key_name + ": " + repr(count_val))
    if cached_tokens > input_tokens:
        raise ValueError("cached_tokens exceeds input_tokens")
    entry = PRICES[model]
    kind = entry["kind"]
    if kind == "tokens":
        if images != 0 or audio_s != 0:
            raise ValueError("image or audio counts given for token model " + model)
        fresh_tokens = input_tokens - cached_tokens
        cost_usd = (
            fresh_tokens * entry["input_usd_per_mtok"]
            + cached_tokens * entry["cached_input_usd_per_mtok"]
            + output_tokens * entry["output_usd_per_mtok"]
        ) / 1e6 + search_queries * WEB_SEARCH_USD_PER_QUERY
        return float(cost_usd)
    if kind == "per_image":
        if (
            input_tokens != 0
            or cached_tokens != 0
            or output_tokens != 0
            or audio_s != 0
            or search_queries != 0
        ):
            raise ValueError("non image counts given for per image model " + model)
        return float(images * entry["usd_per_image"])
    if kind == "per_audio_s":
        if (
            input_tokens != 0
            or cached_tokens != 0
            or output_tokens != 0
            or images != 0
            or search_queries != 0
        ):
            raise ValueError("non audio counts given for per audio model " + model)
        return float(audio_s * entry["usd_per_s"])
    if kind == "free":
        if images != 0 or audio_s != 0 or search_queries != 0:
            raise ValueError("image, audio or search counts given for free model " + model)
        return 0.0
    raise ValueError("unknown kind for model " + model)


class Ledger:
    """JSON lines ledger of call costs in USD. Missing file means zero spent."""

    def __init__(
        self,
        path: Any,
        *,
        study_cap_usd: float = 5.0,
        total_cap_usd: float = 100.0,
        live_run_cap_usd: float = 2.0,
        live_daily_cap_usd: float = 5.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._path = Path(path)
        self.study_cap_usd = study_cap_usd
        self.total_cap_usd = total_cap_usd
        self.live_run_cap_usd = live_run_cap_usd
        self.live_daily_cap_usd = live_daily_cap_usd
        self._clock = clock

    def record(
        self,
        run_id: str,
        stage: str,
        model: str,
        *,
        live: bool = False,
        **usage: Any,
    ) -> dict:
        """Append one row with cost in USD. Never refuses on caps."""
        for key_name in usage:
            if key_name not in _ALLOWED_USAGE_KEYS:
                raise ValueError("unknown usage key: " + str(key_name))
        cost_usd = call_cost_usd(model, **usage)  # type: ignore[arg-type]
        row = {
            "ts_unix": float(self._clock()),
            "run_id": run_id,
            "stage": stage,
            "model": model,
            "live": bool(live),
            "usage": dict(usage),
            "cost_usd": float(cost_usd),
        }
        parent = self._path.parent
        if str(parent) and not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
        return row

    def rows(self) -> list[dict]:
        """All ledger rows. A corrupt line in the file raises ValueError."""
        if not self._path.exists():
            return []
        text = self._path.read_text(encoding="utf-8")
        out_rows: list[dict] = []
        for lineno_1, line in enumerate(text.splitlines(), start=1):
            if line.strip() == "":
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError("bad ledger line " + str(lineno_1)) from exc
            if not isinstance(row, dict):
                raise ValueError("bad ledger line " + str(lineno_1))
            out_rows.append(row)
        return out_rows

    def spent_usd(
        self, run_id: str | None = None, live_day: dt.date | None = None
    ) -> float:
        """Total spent in USD, optionally for one run or one live UTC day."""
        total_usd = 0.0
        for row in self.rows():
            if run_id is not None and row.get("run_id") != run_id:
                continue
            if live_day is not None:
                if not row.get("live"):
                    continue
                ts_unix = float(row["ts_unix"])
                row_day = dt.datetime.fromtimestamp(ts_unix, tz=dt.timezone.utc).date()
                if row_day != live_day:
                    continue
            total_usd += float(row["cost_usd"])
        return total_usd

    def check(self, run_id: str, estimate_usd: float, *, live: bool = False) -> None:
        """Raise BudgetExceeded if estimate in USD would break any cap."""
        if estimate_usd < 0:
            raise ValueError("negative estimate: " + repr(estimate_usd))
        run_spent_usd = self.spent_usd(run_id=run_id)
        if run_spent_usd + estimate_usd > self.study_cap_usd + _TOL_USD:
            raise BudgetExceeded(
                "study cap exceeded: run "
                + str(run_id)
                + " spent "
                + str(run_spent_usd)
                + " USD plus estimate "
                + str(estimate_usd)
                + " USD above cap "
                + str(self.study_cap_usd)
                + " USD"
            )
        total_spent_usd = self.spent_usd()
        if total_spent_usd + estimate_usd > self.total_cap_usd + _TOL_USD:
            raise BudgetExceeded(
                "total cap exceeded: ledger spent "
                + str(total_spent_usd)
                + " USD plus estimate "
                + str(estimate_usd)
                + " USD above cap "
                + str(self.total_cap_usd)
                + " USD"
            )
        if live:
            if run_spent_usd + estimate_usd > self.live_run_cap_usd + _TOL_USD:
                raise BudgetExceeded(
                    "live run cap exceeded: run "
                    + str(run_id)
                    + " spent "
                    + str(run_spent_usd)
                    + " USD plus estimate "
                    + str(estimate_usd)
                    + " USD above cap "
                    + str(self.live_run_cap_usd)
                    + " USD"
                )
            today = dt.datetime.fromtimestamp(
                float(self._clock()), tz=dt.timezone.utc
            ).date()
            day_spent_usd = self.spent_usd(live_day=today)
            if day_spent_usd + estimate_usd > self.live_daily_cap_usd + _TOL_USD:
                raise BudgetExceeded(
                    "live daily cap exceeded: day "
                    + str(today)
                    + " spent "
                    + str(day_spent_usd)
                    + " USD plus estimate "
                    + str(estimate_usd)
                    + " USD above cap "
                    + str(self.live_daily_cap_usd)
                    + " USD"
                )
