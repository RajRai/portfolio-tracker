import csv
import math
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import requests

try:
    import yfinance as yf
except ImportError:
    yf = None


POLYGON_BASE_URL = os.environ.get("POLYGON_BASE_URL", "https://api.polygon.io")
MAX_SOURCE_TICKERS = 1000
MAX_EARNINGS_TICKERS = 300


class ToolDataError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _to_float(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        out = float(str(value).replace(",", "").replace("$", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def normalize_tickers(values) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        raw_items = re.split(r"[\s,;]+", values)
    else:
        raw_items = []
        for value in values:
            raw_items.extend(re.split(r"[\s,;]+", str(value)))

    seen = set()
    tickers = []
    for item in raw_items:
        ticker = item.strip().upper().lstrip("$")
        if not ticker or ticker in seen:
            continue
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9.\-]*", ticker):
            continue
        seen.add(ticker)
        tickers.append(ticker)
    return tickers


def _polygon_key(api_key: str | None = None) -> str:
    key = api_key or os.environ.get("POLYGON_API_KEY")
    if not key:
        raise ToolDataError("Missing POLYGON_API_KEY", 400)
    return key


def _polygon_error(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    message = payload.get("error") or payload.get("message") or response.text.strip()
    return message or f"Polygon request failed with status {response.status_code}"


def _polygon_get(path_or_url: str, params: dict | None = None, api_key: str | None = None) -> dict:
    key = _polygon_key(api_key)
    url = path_or_url if path_or_url.startswith("http") else f"{POLYGON_BASE_URL}{path_or_url}"
    request_params = dict(params or {})
    request_params["apiKey"] = key
    response = requests.get(url, params=request_params, timeout=20)
    if response.status_code >= 400:
        raise ToolDataError(_polygon_error(response), 502)
    return response.json()


def _polygon_paginated(path: str, params: dict, api_key: str | None = None, max_pages: int = 20) -> list[dict]:
    results = []
    next_url = path
    next_params = dict(params)
    pages = 0

    while next_url and pages < max_pages:
        payload = _polygon_get(next_url, next_params, api_key)
        results.extend(payload.get("results") or [])
        next_url = payload.get("next_url")
        next_params = {}
        pages += 1

    return results


def _read_csv_rows(path: Path) -> list[dict]:
    with open(path, "r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def portfolio_source(account_id: str, accounts: list[dict], out_dir: Path) -> dict:
    account = next((item for item in accounts if item.get("id") == account_id), None)
    if not account:
        raise ToolDataError("Portfolio was not found", 404)

    weights_path = out_dir / Path(account.get("weights", "")).name
    if not weights_path.exists():
        raise ToolDataError("Portfolio weights file was not found", 404)

    holdings = []
    for row in _read_csv_rows(weights_path):
        ticker = normalize_tickers(row.get("Ticker"))[:1]
        if not ticker:
            continue
        weight = _to_float(row.get("Portfolio Weight (%)"))
        quantity = _to_float(row.get("_Quantity"))
        holdings.append({
            "ticker": ticker[0],
            "name": ticker[0],
            "source_weight": (weight / 100.0) if weight is not None else None,
            "quantity": quantity,
        })

    return _dedupe_holdings({
        "source": {
            "type": "portfolio",
            "label": account.get("name") or account.get("id") or "Portfolio",
            "id": account.get("id"),
        },
        "holdings": holdings,
        "warnings": [],
    })


def _dedupe_holdings(payload: dict) -> dict:
    seen = set()
    holdings = []
    for holding in payload.get("holdings", []):
        ticker = normalize_tickers(holding.get("ticker"))[:1]
        if not ticker or ticker[0] in seen:
            continue
        seen.add(ticker[0])
        holdings.append({**holding, "ticker": ticker[0]})
        if len(holdings) >= MAX_SOURCE_TICKERS:
            payload.setdefault("warnings", []).append(
                f"Limited the source list to {MAX_SOURCE_TICKERS} tickers."
            )
            break
    payload["holdings"] = holdings
    payload["tickers"] = [holding["ticker"] for holding in holdings]
    return payload


def _polygon_fund_holdings(fund_ticker: str, api_key: str | None = None) -> dict:
    results = _polygon_paginated(
        "/etf-global/v1/constituents",
        {
            "composite_ticker": fund_ticker,
            "limit": 5000,
            "sort": "weight.desc",
        },
        api_key,
        max_pages=5,
    )
    holdings = []
    effective_dates = []
    processed_dates = []

    for item in results:
        ticker = normalize_tickers(item.get("constituent_ticker"))[:1]
        if not ticker:
            continue
        effective_dates.append(item.get("effective_date"))
        processed_dates.append(item.get("processed_date"))
        holdings.append({
            "ticker": ticker[0],
            "name": item.get("constituent_name") or ticker[0],
            "source_weight": _to_float(item.get("weight")),
            "market_value": _to_float(item.get("market_value")),
            "shares_held": _to_float(item.get("shares_held")),
            "asset_class": item.get("asset_class"),
            "security_type": item.get("security_type"),
        })

    return _dedupe_holdings({
        "source": {
            "type": "fund",
            "label": fund_ticker,
            "id": fund_ticker,
            "provider": "Polygon ETF Global",
            "effective_date": next((value for value in effective_dates if value), None),
            "processed_date": next((value for value in processed_dates if value), None),
        },
        "holdings": holdings,
        "warnings": [],
    })


def _yfinance_fund_holdings(fund_ticker: str) -> dict:
    if yf is None:
        raise ToolDataError("yfinance is required for fund holdings fallback", 502)

    frame = yf.Ticker(fund_ticker).funds_data.top_holdings
    if frame is None or frame.empty:
        raise ToolDataError("No holdings were found for that fund ticker", 404)

    holdings = []
    for symbol, row in frame.iterrows():
        ticker = normalize_tickers(symbol)[:1]
        if not ticker:
            continue
        holdings.append({
            "ticker": ticker[0],
            "name": row.get("Name") or ticker[0],
            "source_weight": _to_float(row.get("Holding Percent")),
        })

    return _dedupe_holdings({
        "source": {
            "type": "fund",
            "label": fund_ticker,
            "id": fund_ticker,
            "provider": "Yahoo Finance top holdings",
        },
        "holdings": holdings,
        "warnings": [
            "Using Yahoo Finance top holdings because complete ETF constituents were unavailable."
        ],
    })


def fund_source(fund_ticker: str, api_key: str | None = None) -> dict:
    ticker = normalize_tickers(fund_ticker)[:1]
    if not ticker:
        raise ToolDataError("Enter an index fund or ETF ticker", 400)

    fund = ticker[0]
    warnings = []
    try:
        payload = _polygon_fund_holdings(fund, api_key)
        if payload["holdings"]:
            return payload
    except ToolDataError as exc:
        warnings.append(f"Polygon ETF holdings unavailable: {exc}")

    try:
        payload = _yfinance_fund_holdings(fund)
        payload["warnings"] = warnings + payload.get("warnings", [])
        return payload
    except ToolDataError as exc:
        warnings.append(str(exc))

    raise ToolDataError("; ".join(warnings) or "No holdings were found for that fund ticker", 404)


def stock_source(body: dict, accounts: list[dict], out_dir: Path, api_key: str | None = None) -> dict:
    source_type = (body.get("sourceType") or "").strip().lower()
    if source_type == "portfolio":
        return portfolio_source(body.get("accountId"), accounts, out_dir)
    if source_type == "fund":
        return fund_source(body.get("fundTicker"), api_key)
    raise ToolDataError("Choose a portfolio or fund source", 400)


def _fetch_ticker_overviews(tickers: list[str], api_key: str | None = None) -> dict[str, dict]:
    details = {}
    for ticker in tickers:
        payload = _polygon_get(f"/v3/reference/tickers/{quote(ticker, safe='')}", {}, api_key)
        details[ticker] = payload.get("results") or {}
    return details


def market_cap_weights(tickers, api_key: str | None = None) -> dict:
    normalized = normalize_tickers(tickers)
    if not normalized:
        raise ToolDataError("Add at least one stock ticker", 400)

    details = _fetch_ticker_overviews(normalized, api_key)
    rows = []
    total = 0.0

    for ticker in normalized:
        item = details.get(ticker) or {}
        market_cap = _to_float(item.get("market_cap"))
        if market_cap is not None and market_cap > 0:
            total += market_cap
        rows.append({
            "ticker": ticker,
            "name": item.get("name") or ticker,
            "market_cap": market_cap,
            "exchange": item.get("primary_exchange"),
            "type": item.get("type"),
            "currency": item.get("currency_name"),
            "weight": None,
            "note": None if market_cap and market_cap > 0 else "Market cap unavailable",
        })

    for row in rows:
        if total > 0 and row["market_cap"] and row["market_cap"] > 0:
            row["weight"] = row["market_cap"] / total

    rows.sort(key=lambda row: row["weight"] or -1, reverse=True)
    return {
        "tickers": normalized,
        "total_market_cap": total if total > 0 else None,
        "rows": rows,
        "missing": [row["ticker"] for row in rows if row["weight"] is None],
    }


def _parse_date(value: str | None, fallback: date) -> date:
    if not value:
        return fallback
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ToolDataError("Dates must use YYYY-MM-DD format", 400) from exc


def earnings_calendar(tickers, start: str | None = None, end: str | None = None, api_key: str | None = None) -> dict:
    normalized = normalize_tickers(tickers)
    if not normalized:
        raise ToolDataError("Add at least one stock ticker", 400)
    if len(normalized) > MAX_EARNINGS_TICKERS:
        raise ToolDataError(f"Earnings calendar is limited to {MAX_EARNINGS_TICKERS} tickers per request", 400)
    key = _polygon_key(api_key)

    today = date.today()
    start_date = _parse_date(start, today)
    end_date = _parse_date(end, today + timedelta(days=90))
    if end_date < start_date:
        raise ToolDataError("End date must be on or after start date", 400)
    if (end_date - start_date).days > 366:
        raise ToolDataError("Date range must be 366 days or less", 400)

    events = []
    warnings = []
    for ticker in normalized:
        try:
            payload = _polygon_get(
                "/benzinga/v1/earnings",
                {
                    "ticker": ticker,
                    "date.gte": start_date.isoformat(),
                    "date.lte": end_date.isoformat(),
                    "sort": "date.asc",
                    "limit": 50000,
                },
                key,
            )
        except ToolDataError as exc:
            warnings.append(f"{ticker}: {exc}")
            continue

        for item in payload.get("results") or []:
            events.append({
                "ticker": item.get("ticker") or ticker,
                "company_name": item.get("company_name"),
                "date": item.get("date"),
                "time": item.get("time"),
                "date_status": item.get("date_status"),
                "fiscal_period": item.get("fiscal_period"),
                "fiscal_year": item.get("fiscal_year"),
                "importance": item.get("importance"),
                "estimated_eps": _to_float(item.get("estimated_eps")),
                "actual_eps": _to_float(item.get("actual_eps")),
                "eps_surprise_percent": _to_float(item.get("eps_surprise_percent")),
                "estimated_revenue": _to_float(item.get("estimated_revenue")),
                "actual_revenue": _to_float(item.get("actual_revenue")),
                "revenue_surprise_percent": _to_float(item.get("revenue_surprise_percent")),
                "currency": item.get("currency"),
                "last_updated": item.get("last_updated"),
            })

    events.sort(key=lambda item: (item.get("date") or "", item.get("time") or "", item.get("ticker") or ""))
    return {
        "tickers": normalized,
        "start": start_date.isoformat(),
        "end": end_date.isoformat(),
        "events": events,
        "warnings": warnings,
    }
