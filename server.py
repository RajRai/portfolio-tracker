import os
import json
from pathlib import Path
from flask import Flask, send_from_directory, jsonify
from dotenv import load_dotenv

load_dotenv()

# ============================================================
#  Setup
# ============================================================
BASE_DIR = Path(__file__).parent.resolve()
OUT_DIR = BASE_DIR / "out"
CLIENT_DIR = BASE_DIR / "client" / "dist"

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
    app.run(host="0.0.0.0", port=port)
