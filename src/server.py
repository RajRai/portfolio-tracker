import json
import os
import queue
import threading
from urllib.parse import urlencode

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
            day = item.get("day") or {}
            prev_day = item.get("prevDay") or {}
            price = last_trade.get("p")
            if price is None:
                price = day.get("c")

            prev_close = prev_day.get("c")
            if price is None and prev_close is None:
                continue

            out[ticker] = {
                "price": price,
                "prev_close": prev_close,
                "updated": last_trade.get("t") or item.get("updated"),
            }

    return out


def _push_polygon_stock_stream(tickers: list[str], messages: queue.Queue, stop_event: threading.Event):
    api_key = os.environ.get("POLYGON_API_KEY")
    if not api_key:
        messages.put({
            "type": "status",
            "transport": "offline",
            "message": "Missing POLYGON_API_KEY",
        })
        return

    snapshot = _fetch_stock_snapshots(tickers)
    if snapshot:
        messages.put({
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
                messages.put({
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
                        messages.put({
                            "type": "quote",
                            "transport": "stream",
                            "quotes": updates,
                        })
            return
        except Exception as exc:
            last_stream_error = exc

    messages.put({
        "type": "status",
        "transport": "poll",
        "message": f"Live prices: polling every {LIVE_POLL_SECONDS} seconds",
        "detail": str(last_stream_error) if last_stream_error else None,
    })

    while not stop_event.is_set():
        try:
            quotes = _fetch_stock_snapshots(tickers)
            if quotes:
                messages.put({
                    "type": "quote",
                    "transport": "poll",
                    "quotes": quotes,
                })
        except Exception as exc:
            messages.put({
                "type": "status",
                "transport": "poll",
                "message": "Live prices: polling failed",
                "detail": str(exc),
            })
        stop_event.wait(LIVE_POLL_SECONDS)


# ============================================================
#  API: list all accounts
# ============================================================
@app.route("/api/accounts")
def list_accounts():
    """Return list of all portfolio accounts and file URLs."""
    try:
        data = _load_accounts()
    except Exception as e:
        return jsonify({"error": f"Could not read accounts.json: {e}"}), 500

    return jsonify(data)


@app.route("/api/live/stocks/stream")
def stream_live_stocks():
    tickers = _parse_tickers_param(request.args.get("tickers", ""))
    if not tickers:
        return jsonify({"error": "Missing tickers query parameter"}), 400

    def generate():
        messages = queue.Queue()
        stop_event = threading.Event()
        worker = threading.Thread(
            target=_push_polygon_stock_stream,
            args=(tickers, messages, stop_event),
            daemon=True,
        )
        worker.start()

        try:
            yield "retry: 3000\n\n"
            while True:
                try:
                    payload = messages.get(timeout=15)
                    yield f"data: {json.dumps(payload)}\n\n"
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            stop_event.set()
            worker.join(timeout=1)

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
