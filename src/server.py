import copy
import csv
import json
import math
import os
import queue
import threading
from datetime import datetime
from urllib.parse import urlencode
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from flask import Flask, send_from_directory, jsonify, request, Response, stream_with_context
import requests
from websockets.sync.client import connect

from src.util import BASE_DIR

load_dotenv()

# ============================================================
#  Setup
# ============================================================
OUT_DIR = BASE_DIR / "out"
CLIENT_DIR = BASE_DIR / "client" / "dist"
POLYGON_REALTIME_STOCKS_WS_URL = os.environ.get(
    "POLYGON_REALTIME_STOCKS_WS_URL",
    "wss://socket.polygon.io/stocks",
)
POLYGON_DELAYED_STOCKS_WS_URL = os.environ.get(
    "POLYGON_DELAYED_STOCKS_WS_URL",
    "wss://delayed.polygon.io/stocks",
)
LIVE_POLL_SECONDS = 5
LIVE_REPORT_REFRESH_SECONDS = int(os.environ.get("LIVE_REPORT_REFRESH_SECONDS", "5"))
NY_TZ = ZoneInfo("America/New_York")

app = Flask(
    __name__,
    static_folder=str(CLIENT_DIR),
    static_url_path="/"
)

# Only enable CORS in development
if os.environ.get("FLASK_ENV") == "development":
    from flask_cors import CORS
    CORS(app)
    print("⚠️  CORS enabled for development")
else:
    print("✅  Running in production mode (CORS disabled)")

# ============================================================
#  Live quote helpers
# ============================================================
def _load_accounts():
    index_path = OUT_DIR / "accounts.json"
    if not index_path.exists():
        return []

    with open(index_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _parse_tickers_param(raw: str) -> list[str]:
    seen = set()
    tickers = []
    for item in (raw or "").split(","):
        ticker = item.strip().upper()
        if ticker and ticker not in seen:
            seen.add(ticker)
            tickers.append(ticker)
    return tickers


def _chunked(items: list[str], size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _valid_price(value) -> float | None:
    price = _to_float(value)
    if math.isnan(price) or price <= 0:
        return None
    return price


def _first_valid_price(*values) -> float | None:
    for value in values:
        price = _valid_price(value)
        if price is not None:
            return price
    return None


def _resolve_live_price(quote: dict) -> float | None:
    return _first_valid_price(quote.get("price"), quote.get("prev_close"))


def _merge_quote(existing: dict | None, incoming: dict | None) -> dict:
    merged = dict(existing or {})
    incoming = incoming or {}

    price = _valid_price(incoming.get("price"))
    if price is not None:
        merged["price"] = price

    prev_close = _valid_price(incoming.get("prev_close"))
    if prev_close is not None:
        merged["prev_close"] = prev_close

    updated = incoming.get("updated")
    if updated is not None:
        merged["updated"] = updated

    return merged


def _fetch_stock_snapshots(tickers: list[str]) -> dict[str, dict]:
    api_key = os.environ.get("POLYGON_API_KEY")
    if not api_key or not tickers:
        return {}

    out = {}
    for chunk in _chunked(tickers, 50):
        params = urlencode({"tickers": ",".join(chunk), "apiKey": api_key})
        url = f"https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers?{params}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        payload = response.json()

        for item in payload.get("tickers", []):
            ticker = item.get("ticker")
            if not ticker:
                continue

            last_trade = item.get("lastTrade") or {}
            minute = item.get("min") or {}
            day = item.get("day") or {}
            prev_day = item.get("prevDay") or {}
            price = _first_valid_price(
                last_trade.get("p"),
                minute.get("c"),
                day.get("c"),
            )

            prev_close = _valid_price(prev_day.get("c"))
            if price is None and prev_close is None:
                continue

            out[ticker] = {
                "price": price,
                "prev_close": prev_close,
                "updated": last_trade.get("t") or minute.get("t") or item.get("updated"),
            }

    return out


def _to_float(value):
    if value in (None, ""):
        return float("nan")
    try:
        return float(str(value).replace(",", "").replace("$", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return float("nan")


def _format_pct(value: float | None) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    return f"{value * 100:+.2f}%"


def _ny_date_string() -> str:
    return datetime.now(NY_TZ).strftime("%Y-%m-%d")


def _upsert_series_point(series: list[dict], point: dict) -> list[dict]:
    if not series:
        return [point]
    next_series = list(series)
    if next_series[-1].get("t") == point["t"]:
        next_series[-1] = point
    else:
        next_series.append(point)
    return next_series


def _with_live_equity(series: list[dict], live_return: float | None, as_of_date: str) -> list[dict]:
    if not series or live_return is None:
        return series
    next_series = list(series)
    base_idx = len(next_series) - 2 if next_series[-1].get("t") == as_of_date else len(next_series) - 1
    base_idx = max(base_idx, 0)
    base_value = next_series[base_idx].get("v")
    if base_value in (None, 0):
        return series
    return _upsert_series_point(next_series, {"t": as_of_date, "v": base_value * (1 + live_return)})


def _with_live_compounded_return(series: list[dict], live_return: float | None, as_of_date: str) -> list[dict]:
    if not series or live_return is None:
        return series
    next_series = list(series)
    base_idx = len(next_series) - 2 if next_series[-1].get("t") == as_of_date else len(next_series) - 1
    base_idx = max(base_idx, 0)
    base_value = next_series[base_idx].get("v")
    if base_value is None:
        return series
    return _upsert_series_point(
        next_series,
        {"t": as_of_date, "v": (1 + base_value) * (1 + live_return) - 1},
    )


def _clamp_for_multiple(value: float | None) -> float | None:
    if value is None:
        return value
    if value < 0 and value > -0.001:
        return -0.001
    if value >= 0 and value < 0.001:
        return 0.001
    return value


def _read_csv_rows(path: Path) -> tuple[list[str], list[dict]]:
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames or [], list(reader)


def _write_csv_rows(path: Path, fieldnames: list[str], rows: list[dict]):
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp_path, path)


def _write_json(path: Path, payload: dict):
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp_path, path)


def _extract_holdings(rows: list[dict]) -> list[dict]:
    holdings = []
    for row in rows:
        ticker = (row.get("Ticker") or "").strip().upper()
        quantity = _to_float(row.get("_Quantity"))
        basis_approx = _to_float(row.get("_BasisApprox"))
        if ticker and not math.isnan(quantity) and quantity > 0:
            holdings.append({
                "ticker": ticker,
                "quantity": quantity,
                "basis_approx": basis_approx,
            })
    return holdings


def _compute_live_snapshot(holdings: list[dict], benchmark_ticker: str, quotes: dict) -> dict | None:
    prev_close_value = 0.0
    live_value = 0.0
    live_value_by_ticker = {}

    for holding in holdings:
        quote = quotes.get(holding["ticker"]) or {}
        prev_close = _valid_price(quote.get("prev_close"))
        live_price = _resolve_live_price(quote)
        if prev_close is None or live_price is None:
            continue

        ticker_value = holding["quantity"] * live_price
        prev_close_value += holding["quantity"] * prev_close
        live_value += ticker_value
        live_value_by_ticker[holding["ticker"]] = ticker_value

    benchmark_quote = quotes.get(benchmark_ticker) or {}
    benchmark_prev_close = _valid_price(benchmark_quote.get("prev_close"))
    benchmark_live_price = _resolve_live_price(benchmark_quote)

    portfolio_return = None
    benchmark_return = None
    if prev_close_value > 0:
        portfolio_return = live_value / prev_close_value - 1
    if benchmark_prev_close is not None and benchmark_live_price is not None:
        benchmark_return = benchmark_live_price / benchmark_prev_close - 1

    if portfolio_return is None and benchmark_return is None:
        return None

    return {
        "as_of_date": _ny_date_string(),
        "portfolio_return": portfolio_return,
        "benchmark_return": benchmark_return,
        "live_value_by_ticker": live_value_by_ticker,
        "total_live_value": live_value,
    }


def _with_live_weights(weights_series: list[dict], live_snapshot: dict) -> list[dict]:
    if not weights_series:
        return weights_series
    total_live_value = live_snapshot.get("total_live_value") or 0
    if total_live_value <= 0:
        return weights_series

    as_of_date = live_snapshot["as_of_date"]
    live_value_by_ticker = live_snapshot["live_value_by_ticker"]
    out = []
    for series in weights_series:
        out.append({
            **series,
            "points": _upsert_series_point(
                series.get("points", []),
                {
                    "t": as_of_date,
                    "v": live_value_by_ticker.get(series.get("name"), 0.0) / total_live_value,
                },
            ),
        })
    return out


def _apply_live_payload(payload: dict, holdings: list[dict], benchmark_ticker: str, quotes: dict) -> dict | None:
    live_snapshot = _compute_live_snapshot(holdings, benchmark_ticker, quotes)
    if not live_snapshot:
        return None

    next_payload = copy.deepcopy(payload)
    as_of_date = live_snapshot["as_of_date"]
    portfolio_return = live_snapshot["portfolio_return"]
    benchmark_return = live_snapshot["benchmark_return"]

    if portfolio_return is not None:
        next_payload.setdefault("portfolio", {})
        next_payload["portfolio"]["daily"] = _upsert_series_point(
            next_payload["portfolio"].get("daily", []),
            {"t": as_of_date, "v": portfolio_return},
        )
        next_payload["portfolio"]["equity"] = _with_live_equity(
            next_payload["portfolio"].get("equity", []),
            portfolio_return,
            as_of_date,
        )

    if benchmark_return is not None:
        next_payload.setdefault("benchmark", {})
        next_payload["benchmark"]["ticker"] = benchmark_ticker
        next_payload["benchmark"]["daily"] = _upsert_series_point(
            next_payload["benchmark"].get("daily", []),
            {"t": as_of_date, "v": benchmark_return},
        )
        next_payload["benchmark"]["equity"] = _with_live_equity(
            next_payload["benchmark"].get("equity", []),
            benchmark_return,
            as_of_date,
        )

    if portfolio_return is not None and benchmark_return is not None:
        spread = portfolio_return - benchmark_return
        next_payload.setdefault("spread", {})
        next_payload["spread"]["daily"] = _upsert_series_point(
            next_payload["spread"].get("daily", []),
            {"t": as_of_date, "v": spread},
        )
        next_payload["spread"]["cumulative"] = _with_live_compounded_return(
            next_payload["spread"].get("cumulative", []),
            spread,
            as_of_date,
        )
        next_payload.setdefault("multiple", {})
        next_payload["multiple"]["daily"] = _upsert_series_point(
            next_payload["multiple"].get("daily", []),
            {
                "t": as_of_date,
                "v": _clamp_for_multiple(portfolio_return) / _clamp_for_multiple(benchmark_return),
            },
        )

    next_payload["weights"] = _with_live_weights(next_payload.get("weights", []), live_snapshot)
    return next_payload


def _refresh_weights_rows(rows: list[dict], quotes: dict) -> list[dict]:
    holdings = _extract_holdings(rows)
    if not holdings:
        return rows

    live_snapshot = _compute_live_snapshot(holdings, "SPY", quotes)
    total_live_value = live_snapshot["total_live_value"] if live_snapshot else 0
    live_value_by_ticker = live_snapshot["live_value_by_ticker"] if live_snapshot else {}

    refreshed = []
    for row in rows:
        next_row = dict(row)
        ticker = (row.get("Ticker") or "").strip().upper()
        quantity = _to_float(row.get("_Quantity"))
        basis_approx = _to_float(row.get("_BasisApprox"))
        quote = quotes.get(ticker) or {}
        prev_close = _valid_price(quote.get("prev_close"))
        live_price = _resolve_live_price(quote)

        if total_live_value > 0 and "Portfolio Weight (%)" in next_row and ticker in live_value_by_ticker:
            next_row["Portfolio Weight (%)"] = f"{100 * live_value_by_ticker[ticker] / total_live_value:.2f}%"

        if "Today G/L" in next_row:
            if prev_close is not None and live_price is not None:
                next_row["Today G/L"] = _format_pct(live_price / prev_close - 1)
            else:
                next_row["Today G/L"] = "—"

        if "Total G/L (approx.)" in next_row:
            if live_price is not None and not math.isnan(quantity) and not math.isnan(basis_approx) and basis_approx > 0:
                next_row["Total G/L (approx.)"] = _format_pct((live_price * quantity) / basis_approx - 1)
            else:
                next_row["Total G/L (approx.)"] = "—"

        refreshed.append(next_row)

    return refreshed


def _stream_polygon_stock_feed(tickers: list[str], emit, stop_event: threading.Event):
    api_key = os.environ.get("POLYGON_API_KEY")
    if not api_key:
        emit({
            "type": "status",
            "transport": "offline",
            "message": "Missing POLYGON_API_KEY",
        })
        return

    snapshot = _fetch_stock_snapshots(tickers)
    if snapshot:
        emit({
            "type": "snapshot",
            "transport": "snapshot",
            "quotes": snapshot,
        })

    stream_targets = [
        (POLYGON_REALTIME_STOCKS_WS_URL, "Live prices: Polygon streaming"),
        (POLYGON_DELAYED_STOCKS_WS_URL, "Live prices: Polygon streaming (delayed)"),
    ]
    last_stream_error = None

    for ws_url, status_message in stream_targets:
        try:
            with connect(ws_url, open_timeout=10, close_timeout=2) as ws:
                ws.send(json.dumps({"action": "auth", "params": api_key}))

                auth_ok = False
                while not auth_ok and not stop_event.is_set():
                    raw = ws.recv(timeout=5)
                    events = json.loads(raw)
                    if isinstance(events, dict):
                        events = [events]
                    for event in events:
                        if event.get("ev") != "status":
                            continue
                        status = str(event.get("status", "")).lower()
                        if "auth" in status and "success" in status:
                            auth_ok = True
                            break
                        if "error" in status or "failed" in status:
                            raise RuntimeError(event.get("message") or "Polygon auth failed")

                params = ",".join(f"T.{ticker}" for ticker in tickers)
                ws.send(json.dumps({"action": "subscribe", "params": params}))
                emit({
                    "type": "status",
                    "transport": "stream",
                    "message": status_message,
                })

                while not stop_event.is_set():
                    try:
                        raw = ws.recv(timeout=1)
                    except TimeoutError:
                        continue

                    events = json.loads(raw)
                    if isinstance(events, dict):
                        events = [events]

                    updates = {}
                    for event in events:
                        if event.get("ev") == "T" and event.get("sym") in tickers:
                            updates[event["sym"]] = {
                                "price": event.get("p"),
                                "updated": event.get("t"),
                            }
                        elif event.get("ev") == "status":
                            status = str(event.get("status", "")).lower()
                            if "error" in status:
                                raise RuntimeError(event.get("message") or "Polygon stream error")

                    if updates:
                        emit({
                            "type": "quote",
                            "transport": "stream",
                            "quotes": updates,
                        })
            return
        except Exception as exc:
            last_stream_error = exc

    emit({
        "type": "status",
        "transport": "poll",
        "message": f"Live prices: updating every {LIVE_POLL_SECONDS} seconds",
        "detail": str(last_stream_error) if last_stream_error else None,
    })

    while not stop_event.is_set():
        try:
            quotes = _fetch_stock_snapshots(tickers)
            if quotes:
                emit({
                    "type": "quote",
                    "transport": "poll",
                    "quotes": quotes,
                })
        except Exception as exc:
            emit({
                "type": "status",
                "transport": "poll",
                "message": "Live prices: polling failed",
                "detail": str(exc),
            })
        stop_event.wait(LIVE_POLL_SECONDS)


class LiveQuoteHub:
    def __init__(self):
        self._lock = threading.Lock()
        self._clients = {}
        self._quotes = {}
        self._base_tickers = set()
        self._restart_event = threading.Event()
        self._stop_event = threading.Event()
        self._worker = None
        self._next_client_id = 1
        self._status_payload = None

    def start(self):
        with self._lock:
            if self._worker and self._worker.is_alive():
                return
            self._stop_event.clear()
            self._worker = threading.Thread(target=self._run, daemon=True)
            self._worker.start()

    def set_base_tickers(self, tickers: list[str] | set[str]):
        tickers = set(tickers)
        with self._lock:
            prev_union = self._union_tickers()
            if tickers == self._base_tickers:
                return
            self._base_tickers = tickers
            next_union = self._union_tickers()
        self.start()
        if next_union != prev_union:
            self._restart_event.set()

    def subscribe(self, tickers: list[str]):
        tickers_set = set(tickers)
        messages = queue.Queue()
        with self._lock:
            prev_union = self._union_tickers()
            client_id = self._next_client_id
            self._next_client_id += 1
            self._clients[client_id] = {
                "tickers": tickers_set,
                "queue": messages,
            }
            next_union = self._union_tickers()
            status_payload = copy.deepcopy(self._status_payload)
            snapshot = {
                ticker: copy.deepcopy(quote)
                for ticker, quote in self._quotes.items()
                if ticker in tickers_set
            }
        self.start()
        if status_payload:
            messages.put(status_payload)
        if snapshot:
            messages.put({
                "type": "snapshot",
                "transport": "snapshot",
                "quotes": snapshot,
            })
        if next_union != prev_union:
            self._restart_event.set()
        return client_id, messages

    def unsubscribe(self, client_id: int):
        with self._lock:
            prev_union = self._union_tickers()
            removed = self._clients.pop(client_id, None)
            next_union = self._union_tickers()
        if removed is not None and next_union != prev_union:
            self._restart_event.set()

    def get_quotes(self, tickers: list[str] | set[str] | None = None) -> dict[str, dict]:
        with self._lock:
            if tickers is None:
                return copy.deepcopy(self._quotes)
            tickers_set = set(tickers)
            return {
                ticker: copy.deepcopy(quote)
                for ticker, quote in self._quotes.items()
                if ticker in tickers_set
            }

    def _union_tickers(self):
        client_tickers = set()
        for client in self._clients.values():
            client_tickers.update(client["tickers"])
        return sorted(self._base_tickers | client_tickers)

    def _broadcast(self, payload: dict):
        with self._lock:
            if payload.get("type") == "status":
                self._status_payload = copy.deepcopy(payload)
            normalized_quotes = {}
            if payload.get("quotes"):
                for ticker, quote in payload["quotes"].items():
                    merged = _merge_quote(self._quotes.get(ticker), quote)
                    self._quotes[ticker] = merged
                    normalized_quotes[ticker] = copy.deepcopy(merged)
            clients = [
                (client["tickers"], client["queue"])
                for client in self._clients.values()
            ]

        if payload.get("type") == "status":
            for _, client_queue in clients:
                client_queue.put(copy.deepcopy(payload))
            return

        quotes = normalized_quotes if payload.get("quotes") else {}
        for tickers, client_queue in clients:
            filtered = {ticker: copy.deepcopy(quote) for ticker, quote in quotes.items() if ticker in tickers}
            if filtered:
                client_queue.put({**payload, "quotes": filtered})

    def _run(self):
        while not self._stop_event.is_set():
            self._restart_event.clear()
            with self._lock:
                tickers = self._union_tickers()

            if not tickers:
                self._restart_event.wait(1)
                continue

            _stream_polygon_stock_feed(tickers, self._broadcast, self._restart_event)


class LiveReportRefresher:
    def __init__(self, quote_hub: LiveQuoteHub):
        self._quote_hub = quote_hub
        self._stop_event = threading.Event()
        self._worker = None

    def start(self):
        if self._worker and self._worker.is_alive():
            return
        self._stop_event.clear()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def _load_configs(self):
        configs = []
        for account in _load_accounts():
            weights_path = OUT_DIR / Path(account.get("weights", "")).name
            report_path = OUT_DIR / Path(account.get("report", "")).name
            interactive_path = OUT_DIR / f"{report_path.stem}_interactive.json"
            if not weights_path.exists() or not interactive_path.exists():
                continue

            try:
                fieldnames, rows = _read_csv_rows(weights_path)
                with open(interactive_path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
            except Exception:
                continue

            holdings = _extract_holdings(rows)
            benchmark_ticker = payload.get("benchmark", {}).get("ticker", "SPY")
            watch_tickers = {benchmark_ticker, *[holding["ticker"] for holding in holdings]}
            configs.append({
                "weights_path": weights_path,
                "interactive_path": interactive_path,
                "fieldnames": fieldnames,
                "rows": rows,
                "payload": payload,
                "holdings": holdings,
                "benchmark_ticker": benchmark_ticker,
                "watch_tickers": watch_tickers,
            })
        return configs

    def _run(self):
        while not self._stop_event.is_set():
            configs = self._load_configs()
            base_tickers = sorted({ticker for config in configs for ticker in config["watch_tickers"]})
            self._quote_hub.set_base_tickers(base_tickers)
            quotes = self._quote_hub.get_quotes(base_tickers)

            if quotes:
                for config in configs:
                    try:
                        refreshed_rows = _refresh_weights_rows(config["rows"], quotes)
                        if refreshed_rows != config["rows"]:
                            _write_csv_rows(config["weights_path"], config["fieldnames"], refreshed_rows)

                        refreshed_payload = _apply_live_payload(
                            config["payload"],
                            config["holdings"],
                            config["benchmark_ticker"],
                            quotes,
                        )
                        if refreshed_payload and refreshed_payload != config["payload"]:
                            _write_json(config["interactive_path"], refreshed_payload)
                    except Exception:
                        continue

            self._stop_event.wait(LIVE_REPORT_REFRESH_SECONDS)


quote_hub = LiveQuoteHub()
live_report_refresher = LiveReportRefresher(quote_hub)
_services_started = False
_services_lock = threading.Lock()


def ensure_live_services_started():
    global _services_started
    with _services_lock:
        if _services_started:
            return
        quote_hub.start()
        live_report_refresher.start()
        _services_started = True


# ============================================================
#  API: list all accounts
# ============================================================
@app.route("/api/accounts")
def list_accounts():
    """Return list of all portfolio accounts and file URLs."""
    ensure_live_services_started()
    try:
        data = _load_accounts()
    except Exception as e:
        return jsonify({"error": f"Could not read accounts.json: {e}"}), 500

    return jsonify(data)


@app.route("/api/live/stocks/stream")
def stream_live_stocks():
    ensure_live_services_started()
    tickers = _parse_tickers_param(request.args.get("tickers", ""))
    if not tickers:
        return jsonify({"error": "Missing tickers query parameter"}), 400

    def generate():
        client_id, messages = quote_hub.subscribe(tickers)

        try:
            yield "retry: 3000\n\n"
            while True:
                try:
                    payload = messages.get(timeout=15)
                    yield f"data: {json.dumps(payload)}\n\n"
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            quote_hub.unsubscribe(client_id)

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    }
    return Response(stream_with_context(generate()), mimetype="text/event-stream", headers=headers)

# ============================================================
#  Serve QuantStats HTML reports
# ============================================================
@app.route("/reports/<path:filename>")
def serve_report(filename):
    """Serve QuantStats HTML reports (read-only)."""
    report_path = OUT_DIR / filename
    if not report_path.exists():
        return jsonify({"error": f"Report {filename} not found"}), 404
    return send_from_directory(OUT_DIR, filename, mimetype="text/html")

# ============================================================
#  Serve CSV data (weights/trades)
# ============================================================
@app.route("/data/<path:filename>")
def serve_data(filename):
    """Serve CSV files for weights and trades."""
    csv_path = OUT_DIR / filename
    if not csv_path.exists():
        return jsonify({"error": f"Data file {filename} not found"}), 404
    return send_from_directory(OUT_DIR, filename, mimetype="text/csv")

# ============================================================
#  React frontend routes
# ============================================================
@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_frontend(path):
    """
    Serve built React app (client/dist).
    Any route not starting with /api/, /data/, or /reports will fall back to index.html.
    """
    # Let API and file routes through
    if path.startswith("api/") or path.startswith("data/") or path.startswith("reports/"):
        return jsonify({"error": "Not found"}), 404

    target_path = CLIENT_DIR / path
    if target_path.exists() and target_path.is_file():
        return send_from_directory(CLIENT_DIR, path)
    else:
        # React router fallback
        return send_from_directory(CLIENT_DIR, "index.html")

# ============================================================
#  Launch
# ============================================================
if __name__ == "__main__":
    port = int(os.environ.get("FLASK_PORT", 8000))
    print(f"✅ Portfolio API & frontend server running at http://127.0.0.1:{port}")
    app.run(host="0.0.0.0", port=port, threaded=True)
