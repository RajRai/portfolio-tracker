import csv
import math
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import requests

from src.yfinance_cache import yf


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


def _first_dict_value(data: dict | None, *keys):
    if not data:
        return None
    for key in keys:
        value = data.get(key)
        if value is not None:
            return value
    return None


def _fetch_yfinance_market_value(ticker: str) -> dict | None:
    if yf is None:
        return None

    yf_ticker = yf.Ticker(ticker)
    fast_info = {}
    info = {}

    try:
        fast_info = dict(yf_ticker.fast_info or {})
    except Exception:
        fast_info = {}

    market_cap = _to_float(_first_dict_value(fast_info, "market_cap", "marketCap"))
    if market_cap is not None and market_cap > 0:
        return {
            "market_cap": market_cap,
            "method": "Yahoo market cap",
            "price": _to_float(_first_dict_value(fast_info, "last_price", "lastPrice", "regularMarketPrice")),
            "shares_outstanding": None,
        }

    try:
        info = yf_ticker.info or {}
    except Exception:
        info = {}

    market_cap = _to_float(_first_dict_value(info, "marketCap"))
    if market_cap is not None and market_cap > 0:
        return {
            "market_cap": market_cap,
            "method": "Yahoo market cap",
            "price": _to_float(_first_dict_value(info, "regularMarketPrice", "currentPrice", "navPrice")),
            "shares_outstanding": _to_float(_first_dict_value(info, "sharesOutstanding", "impliedSharesOutstanding")),
        }

    price = _to_float(_first_dict_value(
        fast_info,
        "last_price",
        "lastPrice",
        "regularMarketPrice",
        "navPrice",
    ))
    if price is None:
        price = _to_float(_first_dict_value(
            info,
            "regularMarketPrice",
            "currentPrice",
            "previousClose",
            "navPrice",
        ))

    shares = _to_float(_first_dict_value(
        info,
        "sharesOutstanding",
        "impliedSharesOutstanding",
    ))
    if shares is None:
        shares = _to_float(_first_dict_value(
            fast_info,
            "shares",
            "sharesOutstanding",
            "impliedSharesOutstanding",
        ))

    if price is not None and price > 0 and shares is not None and shares > 0:
        return {
            "market_cap": price * shares,
            "method": "Price x shares outstanding",
            "price": price,
            "shares_outstanding": shares,
        }

    total_assets = _to_float(_first_dict_value(info, "totalAssets", "netAssets"))
    if total_assets is not None and total_assets > 0:
        return {
            "market_cap": total_assets,
            "method": "Total assets",
            "price": price,
            "shares_outstanding": shares,
        }

    return None


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
        valuation = None
        method = "Polygon market cap" if market_cap is not None and market_cap > 0 else None
        price = None
        shares_outstanding = None
        note = None

        if market_cap is None or market_cap <= 0:
            valuation = _fetch_yfinance_market_value(ticker)
            if valuation:
                market_cap = valuation["market_cap"]
                method = valuation["method"]
                price = valuation.get("price")
                shares_outstanding = valuation.get("shares_outstanding")

        if market_cap is not None and market_cap > 0:
            total += market_cap
        else:
            note = "Market value unavailable"

        rows.append({
            "ticker": ticker,
            "name": item.get("name") or ticker,
            "market_cap": market_cap,
            "market_value": market_cap,
            "valuation_method": method,
            "price": price,
            "shares_outstanding": shares_outstanding,
            "exchange": item.get("primary_exchange"),
            "type": item.get("type"),
            "currency": item.get("currency_name"),
            "weight": None,
            "note": note,
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


def _date_from_any(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if hasattr(value, "date"):
        try:
            return value.date()
        except (TypeError, ValueError):
            pass
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except ValueError:
        return None


def _time_from_any(value) -> str | None:
    if not hasattr(value, "time"):
        return None
    try:
        event_time = value.time()
    except (TypeError, ValueError):
        return None
    if event_time.hour == 0 and event_time.minute == 0 and event_time.second == 0:
        return None
    return event_time.strftime("%H:%M:%S")


def _calendar_dates(calendar: dict) -> list[date]:
    raw_dates = calendar.get("Earnings Date") if calendar else None
    if raw_dates is None:
        return []
    if not isinstance(raw_dates, list):
        raw_dates = [raw_dates]
    return [event_date for event_date in (_date_from_any(value) for value in raw_dates) if event_date is not None]


def _yfinance_earnings_events(ticker: str, start_date: date, end_date: date) -> tuple[list[dict], list[str]]:
    if yf is None:
        raise ToolDataError("yfinance is required for earnings calendar data", 502)

    warnings = []
    yf_ticker = yf.Ticker(ticker)
    calendar = {}
    events = []
    seen_dates = set()

    try:
        frame = yf_ticker.get_earnings_dates(limit=100)
    except Exception as exc:
        frame = None
        warnings.append(f"{ticker}: Yahoo earnings dates unavailable: {exc}")

    if frame is not None and not frame.empty:
        for event_dt, row in frame.iterrows():
            event_date = _date_from_any(event_dt)
            if event_date is None or event_date < start_date or event_date > end_date:
                continue

            estimated_eps = _to_float(row.get("EPS Estimate"))
            actual_eps = _to_float(row.get("Reported EPS"))
            surprise_percent = _to_float(row.get("Surprise(%)"))
            seen_dates.add(event_date)
            events.append({
                "ticker": ticker,
                "company_name": None,
                "date": event_date.isoformat(),
                "time": _time_from_any(event_dt),
                "date_status": "reported" if actual_eps is not None else "estimated",
                "fiscal_period": None,
                "fiscal_year": None,
                "importance": None,
                "estimated_eps": estimated_eps,
                "actual_eps": actual_eps,
                "eps_surprise_percent": surprise_percent,
                "estimated_revenue": None,
                "actual_revenue": None,
                "revenue_surprise_percent": None,
                "currency": None,
                "last_updated": None,
                "provider": "Yahoo Finance",
            })

    try:
        calendar = yf_ticker.calendar or {}
    except Exception as exc:
        warnings.append(f"{ticker}: Yahoo calendar unavailable: {exc}")

    if calendar:
        for event_date in _calendar_dates(calendar):
            if event_date < start_date or event_date > end_date:
                continue
            estimated_eps = _to_float(calendar.get("Earnings Average"))
            estimated_revenue = _to_float(calendar.get("Revenue Average"))
            if event_date in seen_dates:
                for event in events:
                    if event["date"] == event_date.isoformat():
                        event["estimated_eps"] = event["estimated_eps"] if event["estimated_eps"] is not None else estimated_eps
                        event["estimated_revenue"] = estimated_revenue
                continue
            events.append({
                "ticker": ticker,
                "company_name": None,
                "date": event_date.isoformat(),
                "time": None,
                "date_status": "estimated",
                "fiscal_period": None,
                "fiscal_year": None,
                "importance": None,
                "estimated_eps": estimated_eps,
                "actual_eps": None,
                "eps_surprise_percent": None,
                "estimated_revenue": estimated_revenue,
                "actual_revenue": None,
                "revenue_surprise_percent": None,
                "currency": None,
                "last_updated": None,
                "provider": "Yahoo Finance",
            })

    return events, warnings


def earnings_calendar(tickers, start: str | None = None, end: str | None = None, api_key: str | None = None) -> dict:
    normalized = normalize_tickers(tickers)
    if not normalized:
        raise ToolDataError("Add at least one stock ticker", 400)
    if len(normalized) > MAX_EARNINGS_TICKERS:
        raise ToolDataError(f"Earnings calendar is limited to {MAX_EARNINGS_TICKERS} tickers per request", 400)

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
            ticker_events, ticker_warnings = _yfinance_earnings_events(ticker, start_date, end_date)
        except ToolDataError as exc:
            warnings.append(f"{ticker}: {exc}")
            continue

        events.extend(ticker_events)
        warnings.extend(ticker_warnings)

    events.sort(key=lambda item: (item.get("date") or "", item.get("time") or "", item.get("ticker") or ""))
    return {
        "tickers": normalized,
        "start": start_date.isoformat(),
        "end": end_date.isoformat(),
        "provider": "Yahoo Finance",
        "events": events,
        "warnings": warnings,
    }
