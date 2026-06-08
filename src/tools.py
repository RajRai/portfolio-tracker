import csv
import json
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
MAX_ALGO_ROWS = 1000


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


def _positive_float(value) -> float | None:
    out = _to_float(value)
    if out is None or out <= 0:
        return None
    return out


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
    try:
        response = requests.get(url, params=request_params, timeout=20)
    except requests.RequestException as exc:
        raise ToolDataError(f"Polygon request failed: {exc.__class__.__name__}", 502) from exc
    if response.status_code >= 400:
        raise ToolDataError(_polygon_error(response), 502)
    return response.json()


def _read_csv_rows(path: Path) -> list[dict]:
    with open(path, "r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _read_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _out_file_path(public_path: str | None, out_dir: Path) -> Path:
    parts = [
        part
        for part in Path(str(public_path or "").lstrip("/")).parts
        if part not in {"reports", "data"}
    ]
    return out_dir.joinpath(*parts) if parts else out_dir


def _portfolio_interactive_path(account: dict, out_dir: Path) -> Path | None:
    report_path = _out_file_path(account.get("report"), out_dir)
    if report_path == out_dir:
        return None
    return report_path.with_name(f"{report_path.stem}_interactive.json")


def _history_window_from_report_payload(payload: dict) -> dict | None:
    meta = payload.get("meta") or {}
    start_date = meta.get("effective_start_date") or meta.get("requested_start_date")
    end_date = meta.get("effective_end_date") or meta.get("requested_end_date")

    if not start_date or not end_date:
        portfolio_daily = payload.get("portfolio", {}).get("daily") or []
        dates = [str(point.get("t")) for point in portfolio_daily if point.get("t")]
        if dates:
            start_date = start_date or min(dates)
            end_date = end_date or max(dates)

    if not start_date or not end_date:
        return None

    return {
        "startDate": str(start_date),
        "endDate": str(end_date),
    }


def _portfolio_weight_holdings_from_csv(weights_path: Path) -> list[dict]:
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
    return holdings


def _weight_history_from_report_payload(payload: dict) -> list[dict]:
    weights_series = payload.get("weights") or []
    history = []
    seen = set()

    for series in weights_series:
        ticker = normalize_tickers(series.get("name"))[:1]
        if not ticker or ticker[0] in seen:
            continue
        seen.add(ticker[0])

        points = []
        for point in series.get("points") or []:
            point_date = str(point.get("t") or "")
            if not point_date:
                continue
            weight = _to_float(point.get("v"))
            points.append({
                "date": point_date,
                "weight": 0.0 if weight is None else weight,
            })
        if not points:
            continue
        history.append({
            "ticker": ticker[0],
            "points": points,
        })

    if not history:
        raise ToolDataError("Historical weights could not be inferred for this portfolio", 404)
    return history


def portfolio_source(account_id: str, accounts: list[dict], out_dir: Path, infer_historical_weights: bool = False) -> dict:
    account = next((item for item in accounts if item.get("id") == account_id), None)
    if not account:
        raise ToolDataError("Portfolio was not found", 404)

    weights_path = _out_file_path(account.get("weights"), out_dir)
    if not weights_path.exists():
        raise ToolDataError("Portfolio weights file was not found", 404)

    interactive_path = _portfolio_interactive_path(account, out_dir)
    report_payload = _read_json(interactive_path) if interactive_path and interactive_path.exists() else None
    history_window = _history_window_from_report_payload(report_payload or {}) if report_payload else None
    holdings = _portfolio_weight_holdings_from_csv(weights_path)
    weight_history = None

    if infer_historical_weights:
        if report_payload is None:
            raise ToolDataError("Portfolio history file was not found", 404)
        weight_history = _weight_history_from_report_payload(report_payload)

    return _dedupe_holdings({
        "source": {
            "type": "portfolio",
            "label": account.get("name") or account.get("id") or "Portfolio",
            "id": account.get("id"),
            "weightSource": "historical" if infer_historical_weights else "current",
            "historyWindow": history_window,
        },
        "holdings": holdings,
        "weightHistory": weight_history,
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


def stock_source(body: dict, accounts: list[dict], out_dir: Path, api_key: str | None = None) -> dict:
    source_type = (body.get("sourceType") or "").strip().lower()
    if source_type == "portfolio":
        return portfolio_source(
            body.get("accountId"),
            accounts,
            out_dir,
            infer_historical_weights=bool(body.get("inferHistoricalWeights")),
        )
    if source_type == "fund":
        raise ToolDataError("Index fund loading was removed. Add those stocks manually.", 400)
    raise ToolDataError("Choose a portfolio source or add stocks manually", 400)


def _chunked(items: list[str], size: int):
    for idx in range(0, len(items), size):
        yield items[idx:idx + size]


def _extract_algo_csv(raw_text: str) -> tuple[list[str] | None, list[list[str]]]:
    text = str(raw_text or "")
    header = None
    rows = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        header_match = re.search(r"\bFINAL_HEADER\s+(.+)$", line)
        if header_match:
            header = next(csv.reader([header_match.group(1)]), [])
            continue

        row_match = re.search(r"\bFINAL_ROW\s+(.+)$", line)
        if row_match:
            rows.append(next(csv.reader([row_match.group(1)]), []))

    if header is not None or rows:
        return header, rows

    csv_lines = [line for line in text.splitlines() if line.strip()]
    if not csv_lines:
        return None, []

    parsed = list(csv.reader(csv_lines))
    if not parsed:
        return None, []
    return parsed[0], parsed[1:]


def _row_dict_from_values(header: list[str], values: list[str]) -> dict[str, str]:
    padded = list(values[:len(header)])
    if len(padded) < len(header):
        padded.extend([""] * (len(header) - len(padded)))
    return {
        str(column).strip(): str(padded[idx]).strip()
        for idx, column in enumerate(header)
    }


def _normalize_header_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").strip().lower())


def _parse_algo_output_rows(raw_text: str) -> tuple[list[dict], list[str]]:
    header, value_rows = _extract_algo_csv(raw_text)
    if not header:
        raise ToolDataError("Paste text that includes algo output rows", 400)

    normalized_header = [str(column).strip() for column in header]
    column_lookup = {
        _normalize_header_name(column): column
        for column in normalized_header
        if str(column).strip()
    }
    required_columns = {
        "ticker": "ticker",
        "targetbuyprice": "targetBuyPrice",
        "targetsellprice": "targetSellPrice",
    }
    missing_columns = [
        display_name
        for lookup_name, display_name in required_columns.items()
        if lookup_name not in column_lookup
    ]
    if missing_columns:
        missing = ", ".join(missing_columns)
        raise ToolDataError(f"Algo output is missing required columns: {missing}", 400)

    parsed_rows = []
    warnings = []

    for row_number, values in enumerate(value_rows, start=1):
        if not any(str(value).strip() for value in values):
            continue

        row = _row_dict_from_values(normalized_header, values)
        ticker_values = normalize_tickers(row.get(column_lookup["ticker"]))
        if not ticker_values:
            warnings.append(f"Row {row_number}: skipped because the ticker was missing or invalid.")
            continue

        target_buy_price = _to_float(row.get(column_lookup["targetbuyprice"]))
        target_sell_price = _to_float(row.get(column_lookup["targetsellprice"]))
        if target_buy_price is None or target_sell_price is None:
            warnings.append(
                f"Row {row_number} ({ticker_values[0]}): skipped because target prices were missing or invalid."
            )
            continue

        parsed_rows.append({
            "rowNumber": row_number,
            "ticker": ticker_values[0],
            "targetBuyPrice": target_buy_price,
            "targetSellPrice": target_sell_price,
            "sourceRow": row,
        })

        if len(parsed_rows) >= MAX_ALGO_ROWS:
            warnings.append(f"Only the first {MAX_ALGO_ROWS} algo rows were processed.")
            break

    if not parsed_rows:
        raise ToolDataError("No valid algo rows were found in the pasted text", 400)

    return parsed_rows, warnings


def _snapshot_quote_from_item(item: dict) -> dict:
    prev_day = item.get("prevDay") or {}
    previous_close = _positive_float(prev_day.get("c"))

    for source_name, source in (
        ("last_trade", item.get("lastTrade") or {}),
        ("minute_close", item.get("min") or {}),
        ("day_close", item.get("day") or {}),
    ):
        live_price = _positive_float(source.get("p"))
        if live_price is None:
            live_price = _positive_float(source.get("c"))
        if live_price is None:
            continue
        return {
            "livePrice": live_price,
            "previousClose": previous_close,
            "priceSource": source_name,
            "priceUpdated": source.get("t") or item.get("updated"),
        }

    return {
        "livePrice": previous_close,
        "previousClose": previous_close,
        "priceSource": "prev_close" if previous_close is not None else None,
        "priceUpdated": item.get("updated"),
    }


def _fetch_polygon_snapshot_quotes(tickers: list[str], api_key: str | None = None) -> dict[str, dict]:
    normalized = normalize_tickers(tickers)
    quotes = {}

    for chunk in _chunked(normalized, 50):
        payload = _polygon_get(
            "/v2/snapshot/locale/us/markets/stocks/tickers",
            {"tickers": ",".join(chunk)},
            api_key,
        )
        results = {
            item.get("ticker"): item
            for item in payload.get("tickers", [])
            if item.get("ticker")
        }
        for ticker in chunk:
            quotes[ticker] = _snapshot_quote_from_item(results.get(ticker) or {})

    return quotes


def _classify_algo_price(live_price: float | None, target_buy_price: float, target_sell_price: float) -> str | None:
    if live_price is None:
        return None
    if live_price <= target_buy_price:
        return "buy"
    if live_price >= target_sell_price:
        return "sell"
    return "hold"


def algo_output_processor(raw_text: str, api_key: str | None = None) -> dict:
    parsed_rows, warnings = _parse_algo_output_rows(raw_text)
    quotes = _fetch_polygon_snapshot_quotes([row["ticker"] for row in parsed_rows], api_key)

    groups = {
        "buy": [],
        "sell": [],
        "hold": [],
    }
    summary = {
        "total": len(parsed_rows),
        "buy": 0,
        "sell": 0,
        "hold": 0,
        "unpriced": 0,
    }

    for row in parsed_rows:
        quote = quotes.get(row["ticker"]) or {}
        live_price = _positive_float(quote.get("livePrice"))
        classification = _classify_algo_price(live_price, row["targetBuyPrice"], row["targetSellPrice"])
        if classification is None:
            summary["unpriced"] += 1
            warnings.append(f"{row['ticker']}: live price was unavailable from Polygon.")
        else:
            summary[classification] += 1
            groups[classification].append(row["ticker"])

    for classification in groups:
        groups[classification] = sorted(groups[classification])

    return {
        "groups": groups,
        "summary": summary,
        "warnings": warnings,
    }


def _fetch_ticker_overviews(tickers: list[str], api_key: str | None = None) -> dict[str, dict]:
    details = {}
    for ticker in tickers:
        try:
            payload = _polygon_get(f"/v3/reference/tickers/{quote(ticker, safe='')}", {}, api_key)
        except ToolDataError as exc:
            details[ticker] = {"_polygon_error": str(exc)}
            continue
        details[ticker] = payload.get("results") or {}
    return details


def _is_etf_overview(item: dict) -> bool:
    ticker_type = str(item.get("type") or "").upper()
    name = str(item.get("name") or "").upper()
    return ticker_type == "ETF" or "ETF" in ticker_type or "EXCHANGE TRADED FUND" in name


def _dict_get(value, *keys):
    for key in keys:
        try:
            item = value.get(key)
        except AttributeError:
            try:
                item = value[key]
            except (KeyError, TypeError):
                item = None
        if item not in (None, ""):
            return item
    return None


def _fetch_yfinance_market_caps(tickers: list[str]) -> dict[str, dict]:
    if yf is None or not tickers:
        return {}

    details = {}
    for ticker in tickers:
        try:
            yf_ticker = yf.Ticker(ticker)
            fast_info = getattr(yf_ticker, "fast_info", {}) or {}
            info = getattr(yf_ticker, "info", {}) or {}
        except Exception as exc:
            details[ticker] = {"_yfinance_error": str(exc)}
            continue

        market_cap = _to_float(_dict_get(fast_info, "marketCap", "market_cap"))
        if market_cap is None:
            market_cap = _to_float(_dict_get(info, "marketCap", "market_cap"))

        details[ticker] = {
            "market_cap": market_cap,
            "name": _dict_get(info, "longName", "shortName", "displayName"),
            "currency": _dict_get(fast_info, "currency") or _dict_get(info, "currency", "financialCurrency"),
            "exchange": _dict_get(fast_info, "exchange") or _dict_get(info, "exchange", "fullExchangeName"),
            "type": _dict_get(info, "quoteType"),
        }
    return details


def market_cap_weights(tickers, api_key: str | None = None) -> dict:
    normalized = normalize_tickers(tickers)
    if not normalized:
        raise ToolDataError("Add at least one stock ticker", 400)

    details = _fetch_ticker_overviews(normalized, api_key)
    yfinance_candidates = [
        ticker
        for ticker in normalized
        if not _is_etf_overview(details.get(ticker) or {})
        and not (_to_float((details.get(ticker) or {}).get("market_cap")) or 0) > 0
    ]
    yfinance_details = _fetch_yfinance_market_caps(yfinance_candidates)
    rows = []
    total = 0.0

    for ticker in normalized:
        item = details.get(ticker) or {}
        fallback_item = yfinance_details.get(ticker) or {}
        polygon_market_cap = _to_float(item.get("market_cap"))
        yfinance_market_cap = _to_float(fallback_item.get("market_cap"))
        market_cap = None
        method = None
        note = None

        if polygon_market_cap is not None and polygon_market_cap > 0:
            market_cap = polygon_market_cap
            method = "Polygon market cap"
        elif yfinance_market_cap is not None and yfinance_market_cap > 0:
            market_cap = yfinance_market_cap
            method = "Yahoo Finance market cap"

        if market_cap is not None and market_cap > 0:
            total += market_cap
        else:
            note = "Market cap unavailable - ETF" if _is_etf_overview(item) else "Market cap unavailable"

        rows.append({
            "ticker": ticker,
            "name": item.get("name") or fallback_item.get("name") or ticker,
            "market_cap": market_cap,
            "market_value": market_cap,
            "valuation_method": method,
            "exchange": item.get("primary_exchange") or fallback_item.get("exchange"),
            "type": item.get("type") or fallback_item.get("type"),
            "currency": item.get("currency_name") or fallback_item.get("currency"),
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


def estimate_market_cap_weights(tickers, latest_prices: dict, as_of_prices: dict, api_key: str | None = None) -> dict:
    normalized = normalize_tickers(tickers)
    if not normalized:
        raise ToolDataError("Add at least one stock ticker", 400)

    details = _fetch_ticker_overviews(normalized, api_key)
    yfinance_candidates = [
        ticker
        for ticker in normalized
        if not _is_etf_overview(details.get(ticker) or {})
        and not (_to_float((details.get(ticker) or {}).get("market_cap")) or 0) > 0
    ]
    yfinance_details = _fetch_yfinance_market_caps(yfinance_candidates)
    rows = []
    total = 0.0

    for ticker in normalized:
        item = details.get(ticker) or {}
        fallback_item = yfinance_details.get(ticker) or {}
        polygon_market_cap = _to_float(item.get("market_cap"))
        yfinance_market_cap = _to_float(fallback_item.get("market_cap"))
        current_market_cap = None
        current_method = None
        note = None

        if polygon_market_cap is not None and polygon_market_cap > 0:
            current_market_cap = polygon_market_cap
            current_method = "Polygon market cap"
        elif yfinance_market_cap is not None and yfinance_market_cap > 0:
            current_market_cap = yfinance_market_cap
            current_method = "Yahoo Finance market cap"

        latest_price = _to_float(latest_prices.get(ticker))
        as_of_price = _to_float(as_of_prices.get(ticker))
        estimated_market_cap = None
        method = None

        if current_market_cap is not None and latest_price and latest_price > 0 and as_of_price and as_of_price > 0:
            estimated_market_cap = current_market_cap * as_of_price / latest_price
            method = f"{current_method} scaled by historical price ratio"
            total += estimated_market_cap
        elif current_market_cap is None:
            note = "Market cap unavailable - ETF" if _is_etf_overview(item) else "Market cap unavailable"
        else:
            note = "Historical price unavailable for estimation"

        rows.append({
            "ticker": ticker,
            "name": item.get("name") or fallback_item.get("name") or ticker,
            "market_cap": estimated_market_cap,
            "market_value": estimated_market_cap,
            "valuation_method": method,
            "exchange": item.get("primary_exchange") or fallback_item.get("exchange"),
            "type": item.get("type") or fallback_item.get("type"),
            "currency": item.get("currency_name") or fallback_item.get("currency"),
            "weight": None,
            "note": note,
            "current_market_cap": current_market_cap,
            "latest_price": latest_price,
            "as_of_price": as_of_price,
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
