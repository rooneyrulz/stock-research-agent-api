"""
General screening mode: given a strategy (and optional sector filter),
scan a bundled candidate universe, score each candidate deterministically,
and return the top-N symbols to feed into the existing per-symbol crew
pipeline in app/pipeline.py.

Deliberately NOT using an LLM to pick stocks here. "Ask a model to choose
good stocks from a list" is exactly the kind of unreliable, hard-to-test,
hard-to-explain step this whole rebuild has been engineering away from --
a numeric scoring function is deterministic, fast, free, and trivially
unit-testable. The LLM's job stays where it adds real value: interpreting
news and writing the final recommendation for the candidates this module
selects.

Concurrency: yfinance calls are synchronous/I/O-bound, so candidates are
scanned in parallel via a thread pool rather than serially -- scanning 50
symbols one at a time would make screening mode noticeably slower than
single_stock/comparison mode for no good reason.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings
from app.logging_config import get_logger, get_trace_logger
from app.schemas import ScreeningCriteria, ScreeningStrategy
from app.tools.yfinance_tools import fetch_market_data

logger = get_logger(__name__)
trace_log = get_trace_logger()


@dataclass(frozen=True)
class ScreeningResult:
    """Return shape of screen_candidates(). Carries the scan counts
    alongside the winning symbols so the API response's ScreeningMeta
    field can be built without re-deriving them."""

    symbols: list[str]
    universe_scanned: int
    candidates_qualified: int


class Candidate:
    """One scanned candidate: its market data plus the score assigned by
    the selected strategy. Kept as a plain internal class (not a Pydantic
    model) since this never crosses an API boundary -- only the final
    ranked symbol list does."""

    __slots__ = ("market_data", "score", "sector", "symbol")

    def __init__(self, symbol: str, sector: str, market_data: dict, score: float):
        self.symbol = symbol
        self.sector = sector
        self.market_data = market_data
        self.score = score


def _load_universe(path: str) -> list[dict]:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(
            f"Screening universe file not found at '{path}'. "
            "Expected a JSON file with a 'candidates' list -- see app/data/nifty50.json."
        )
    with file_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    candidates = data.get("candidates", [])
    if not candidates:
        raise ValueError(f"Screening universe file '{path}' has no candidates.")
    return candidates


def score_candidate(market_data: dict, strategy: ScreeningStrategy) -> float | None:
    """Pure function: given a MarketData-shaped dict, return a numeric
    score for the given strategy (higher = better match), or None if the
    candidate doesn't have enough data to be scored (e.g. too little
    history) or doesn't qualify at all for the strategy.

    Kept deliberately simple for Phase 2 v1 -- these are readable, easily
    adjustable heuristics, not a backtested trading model.
    """
    change_pct = market_data.get("change_pct")
    rsi = market_data.get("rsi_14")
    price = market_data.get("current_price")
    sma_50 = market_data.get("sma_50")

    if change_pct is None or price is None:
        return None

    if strategy == ScreeningStrategy.TOP_GAINERS:
        return change_pct

    if strategy == ScreeningStrategy.OVERSOLD:
        if rsi is None:
            return None
        # Only genuinely oversold candidates qualify (RSI < 35); score is
        # "how oversold", so a lower RSI ranks higher.
        if rsi >= 35:
            return None
        return 35 - rsi

    if strategy == ScreeningStrategy.BREAKOUT:
        if sma_50 is None:
            return None
        # Qualify only if price is above its 50-day SMA; score by how far above.
        if price <= sma_50:
            return None
        return ((price - sma_50) / sma_50) * 100

    # MOMENTUM (default): weighted blend of recent gain and RSI strength,
    # rewarding stocks that are rising without already being deeply
    # overbought (RSI close to 70+ scores worse than RSI around 55-65).
    if rsi is None:
        return change_pct
    rsi_component = 100 - abs(rsi - 60)  # peaks when RSI is near 60
    return (change_pct * 2) + (rsi_component * 0.1)


def _scan_one(candidate: dict, period: str) -> tuple[dict, dict | None, str | None]:
    """Fetch market data for one candidate. Returns (candidate, market_data_or_None, error_or_None).
    Never raises -- failures are reported back for the caller to log/skip,
    consistent with the graceful-degradation pattern used throughout the
    rest of the pipeline."""
    try:
        market_data = fetch_market_data(candidate["symbol"], period=period)
        return candidate, market_data, None
    except Exception as exc:  # noqa: BLE001
        return candidate, None, str(exc)


def screen_candidates(criteria: ScreeningCriteria) -> ScreeningResult:
    """Scan the bundled universe, score, and return the top-N symbols
    (by settings.max_screening_results) matching the given criteria,
    plus how many candidates were scanned/qualified. An empty `symbols`
    list means "no matches", not an error -- callers should treat it as
    a normal (if disappointing) outcome."""
    settings = get_settings()
    universe = _load_universe(settings.screening_universe_path)

    if criteria.sector:
        universe = [
            c
            for c in universe
            if c.get("sector", "").lower() == criteria.sector.lower()
        ]
        if not universe:
            logger.info("screening_sector_no_matches", sector=criteria.sector)
            return ScreeningResult(
                symbols=[], universe_scanned=0, candidates_qualified=0
            )

    scanned: list[Candidate] = []
    failures = 0

    with ThreadPoolExecutor(max_workers=settings.screening_max_workers) as pool:
        futures = [
            pool.submit(_scan_one, candidate, settings.screening_scan_period)
            for candidate in universe
        ]
        for future in as_completed(futures):
            candidate, market_data, error = future.result()
            if error is not None or market_data is None:
                failures += 1
                trace_log.warning(
                    "screening_candidate_scan_failed",
                    symbol=candidate["symbol"],
                    error=error,
                )
                continue
            score = score_candidate(market_data, criteria.strategy)
            if score is None:
                continue  # candidate didn't qualify for this strategy
            scanned.append(
                Candidate(
                    candidate["symbol"], candidate.get("sector", ""), market_data, score
                )
            )

    if failures:
        logger.warning(
            "screening_scan_partial_failures",
            failed_count=failures,
            universe_size=len(universe),
        )

    scanned.sort(key=lambda c: c.score, reverse=True)
    top = scanned[: settings.max_screening_results]

    logger.info(
        "screening_completed",
        strategy=criteria.strategy,
        sector=criteria.sector,
        universe_size=len(universe),
        qualified=len(scanned),
        selected=[c.symbol for c in top],
    )
    return ScreeningResult(
        symbols=[c.symbol for c in top],
        universe_scanned=len(universe),
        candidates_qualified=len(scanned),
    )
