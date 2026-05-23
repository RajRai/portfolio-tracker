export function umamiTrack(eventName, data = {}) {
    try {
        if (typeof window !== "undefined" && window.umami && typeof window.umami.track === "function") {
            window.umami.track(eventName, data);
        }
    } catch {
        // Ignore analytics errors so they never affect the UI.
    }
}

export function trackToolEvent(toolName, action, data = {}) {
    umamiTrack(`${toolName}_${action}`, data);
}

export function serializeTickerList(tickers = []) {
    return tickers.filter(Boolean).join(",");
}

export function serializeHoldings(holdings = []) {
    return holdings
        .filter((holding) => holding?.ticker)
        .map((holding) => `${holding.ticker}:${holding.weight}`)
        .join(",");
}

export function serializeQuery(query) {
    try {
        return JSON.stringify(query);
    } catch {
        return "";
    }
}
