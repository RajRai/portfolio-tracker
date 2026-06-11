import posthog from "posthog-js/dist/module.full.no-external";

const POSTHOG_CONFIG_URL = "/api/posthog/config";
const SENSITIVE_EVENT_KEYS = new Set([
    "account_id",
    "account_name",
    "loaded_tickers",
    "query",
    "query_account_id",
    "query_benchmark_holdings",
    "query_benchmark_source_account_id",
    "query_benchmark_ticker",
    "query_benchmark_tickers",
    "query_portfolio_holdings",
    "query_portfolio_source_account_id",
    "query_portfolio_tickers",
    "query_report_name",
    "query_tickers",
    "selected_account_id",
    "source_label",
]);
const PERSONAL_URL_KEYS = [
    "accountId",
    "benchmarkTicker",
    "reportName",
    "sourceAccountId",
    "tickers",
];

let analyticsBootPromise = null;
let analyticsEnabled = false;
let initialPageviewTracked = false;

const stripQueryString = (value) => String(value || "").split("?")[0];

const sanitizeStringValue = (key, value) => {
    const trimmed = String(value || "").trim();
    if (!trimmed) return undefined;
    if (key === "$current_url" || key === "path" || key.endsWith("_url")) {
        return stripQueryString(trimmed).slice(0, 240);
    }
    return trimmed.slice(0, 240);
};

const shouldDropEventProperty = (key) =>
    SENSITIVE_EVENT_KEYS.has(key) ||
    /(?:^|_)holdings$/.test(key) ||
    /(?:^|_)tickers$/.test(key);

export function sanitizeAnalyticsProperties(properties = {}) {
    const sanitized = {};

    for (const [key, value] of Object.entries(properties || {})) {
        if (shouldDropEventProperty(key) || value == null) continue;

        if (typeof value === "boolean") {
            sanitized[key] = value;
            continue;
        }

        if (typeof value === "number") {
            if (Number.isFinite(value)) {
                sanitized[key] = value;
            }
            continue;
        }

        if (typeof value === "string") {
            const nextValue = sanitizeStringValue(key, value);
            if (nextValue !== undefined) {
                sanitized[key] = nextValue;
            }
        }
    }

    return sanitized;
}

function trackInitialPageview() {
    if (initialPageviewTracked || typeof window === "undefined") return;
    initialPageviewTracked = true;

    const sessionId = typeof posthog.get_session_id === "function" ? posthog.get_session_id() : undefined;
    posthog.capture(
        "$pageview",
        sanitizeAnalyticsProperties({
            $current_url: `${window.location.pathname}${window.location.search}`,
            $session_id: sessionId,
        })
    );
}

function buildPostHogOptions(config) {
    return {
        api_host: config.apiHost,
        ui_host: config.uiHost || null,
        defaults: "2026-01-30",
        disable_external_dependency_loading: true,
        autocapture: {
            dom_event_allowlist: ["click", "submit"],
            element_allowlist: ["a", "button", "form"],
        },
        capture_exceptions: true,
        capture_pageleave: "if_capture_pageview",
        capture_pageview: "history_change",
        capture_performance: true,
        custom_personal_data_properties: PERSONAL_URL_KEYS,
        mask_all_element_attributes: true,
        mask_all_text: true,
        mask_personal_data_properties: true,
        respect_dnt: Boolean(config.respectDnt),
        sanitize_properties: sanitizeAnalyticsProperties,
        session_recording: {
            maskAllInputs: true,
            maskTextSelector: "*",
            maskCapturedNetworkRequestFn: (request) => {
                if (request && typeof request.name === "string") {
                    request.name = stripQueryString(request.name);
                }
                return request;
            },
        },
        loaded: (instance) => {
            const hasOptedOut =
                typeof instance.has_opted_out_capturing === "function"
                    ? instance.has_opted_out_capturing()
                    : undefined;
            const isCapturing =
                typeof instance.is_capturing === "function"
                    ? instance.is_capturing()
                    : undefined;

            if (typeof window !== "undefined") {
                window.__portfolioAnalyticsStatus = {
                    enabled: true,
                    apiHost: config.apiHost,
                    uiHost: config.uiHost || null,
                    respectDnt: Boolean(config.respectDnt),
                    distinctId:
                        typeof instance.get_distinct_id === "function"
                            ? instance.get_distinct_id()
                            : undefined,
                    sessionId:
                        typeof instance.get_session_id === "function"
                            ? instance.get_session_id()
                            : undefined,
                    hasOptedOut,
                    isCapturing,
                };
            }

            if (Boolean(config.respectDnt) && hasOptedOut) {
                console.warn("PostHog capture is disabled because Do Not Track is enabled in this browser.");
            }
            if (config.debug || window.location.search.includes("__posthog_debug=true")) {
                instance.debug();
            }
            trackInitialPageview();
        },
    };
}

export async function bootAnalytics() {
    if (analyticsBootPromise) return analyticsBootPromise;

    analyticsBootPromise = fetch(POSTHOG_CONFIG_URL)
        .then(async (response) => {
            if (!response.ok) return false;
            const config = await response.json().catch(() => ({}));
            if (!config?.enabled || !config?.projectToken || !config?.apiHost) {
                analyticsEnabled = false;
                if (typeof window !== "undefined") {
                    window.__portfolioAnalyticsStatus = {
                        enabled: false,
                        reason: "missing_config",
                        config,
                    };
                }
                return false;
            }

            posthog.init(config.projectToken, buildPostHogOptions(config));
            analyticsEnabled = true;
            return true;
        })
        .catch(() => {
            analyticsEnabled = false;
            if (typeof window !== "undefined") {
                window.__portfolioAnalyticsStatus = {
                    enabled: false,
                    reason: "config_fetch_failed",
                };
            }
            return false;
        });

    return analyticsBootPromise;
}

async function captureEvent(eventName, data = {}) {
    const enabled = await bootAnalytics();
    if (!enabled) return;
    posthog.capture(eventName, sanitizeAnalyticsProperties(data));
}

export async function getAnalyticsRequestHeaders() {
    const enabled = await bootAnalytics();
    if (!enabled) return {};

    const headers = {};
    const distinctId = typeof posthog.get_distinct_id === "function" ? posthog.get_distinct_id() : "";
    const sessionId = typeof posthog.get_session_id === "function" ? posthog.get_session_id() : "";

    if (distinctId) {
        headers["X-PostHog-Distinct-Id"] = distinctId;
    }
    if (sessionId) {
        headers["X-PostHog-Session-Id"] = sessionId;
    }

    return headers;
}

export function umamiTrack(eventName, data = {}) {
    void captureEvent(eventName, data);
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
