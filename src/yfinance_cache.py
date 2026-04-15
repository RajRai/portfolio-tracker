from src.util import BASE_DIR

try:
    import yfinance as yf
except ImportError:
    yf = None


YFINANCE_CACHE_DIR = BASE_DIR / "data" / ".cache" / "yfinance"
YFINANCE_HISTORY_CACHE_DIR = YFINANCE_CACHE_DIR / "history"

YFINANCE_HISTORY_CACHE_DIR.mkdir(parents=True, exist_ok=True)

if yf is not None:
    yf.set_tz_cache_location(str(YFINANCE_CACHE_DIR))
