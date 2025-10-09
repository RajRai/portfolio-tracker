import os

from flask import Flask, send_from_directory, jsonify, Response
from pathlib import Path
import json
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# Base output directory for generated files
OUT_DIR = Path("out").resolve()

# Only enable CORS in development
if os.environ.get("FLASK_ENV") == "development":
    from flask_cors import CORS
    CORS(app)
    print("⚠️  CORS enabled for development")
else:
    print("✅  Running in production mode (CORS disabled)")

# ============================================================
#  API: list all accounts
# ============================================================
@app.route("/api/accounts")
def list_accounts():
    """Return list of all portfolio accounts and file URLs."""
    index_path = OUT_DIR / "accounts.json"
    if not index_path.exists():
        return jsonify([])

    try:
        with open(index_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return jsonify({"error": f"Could not read accounts.json: {e}"}), 500

    return jsonify(data)


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
#  Root route
# ============================================================
@app.route("/")
def index():
    """Simple status message."""
    return jsonify({
        "message": "Portfolio server is running",
        "available_routes": {
            "/api/accounts": "List all accounts",
            "/reports/<file>": "QuantStats HTML report",
            "/data/<file>": "CSV data (weights, trades)"
        }
    })


# ============================================================
#  Launch
# ============================================================
if __name__ == "__main__":
    port = os.environ.get("FLASK_PORT") if os.environ.get("FLASK_PORT") else 8000
    print(f"✅ Portfolio API server running at http://127.0.0.1:{port}")
    app.run(host="0.0.0.0", port=port, debug=True)
