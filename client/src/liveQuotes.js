export const nyDateString = () => {
    const parts = new Intl.DateTimeFormat("en-US", {
        timeZone: "America/New_York",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
    }).formatToParts(new Date());
    const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
    return `${values.year}-${values.month}-${values.day}`;
};

const normalizeTimestampMs = (value) => {
    if (value == null || value === "") return null;
    const raw = Number(value);
    if (!Number.isFinite(raw)) return null;

    const absTs = Math.abs(raw);
    if (absTs >= 1e17) return raw / 1e6;
    if (absTs >= 1e14) return raw / 1e3;
    if (absTs >= 1e11) return raw;
    return raw * 1000;
};

const formatCompactNyTimestamp = (timestampMs) => {
    const date = new Date(timestampMs);
    if (Number.isNaN(date.getTime())) return null;

    const parts = new Intl.DateTimeFormat("en-US", {
        timeZone: "America/New_York",
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
    }).formatToParts(date);
    const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
    if (!values.month || !values.day || !values.hour || !values.minute || !values.dayPeriod) {
        return null;
    }
    return `${values.month} ${values.day}, ${values.hour}:${values.minute} ${values.dayPeriod} ET`;
};

const validPrice = (value) => {
    if (value == null) return null;
    const n = Number(String(value).replace(/[,$%]/g, "").trim());
    return Number.isFinite(n) && n > 0 ? n : null;
};

const quotePriceDate = (quote) => {
    if (!quote?.price_date) return null;
    return String(quote.price_date).slice(0, 10);
};

export const resolveLiveQuotePrices = (quote, asOfDate = nyDateString()) => {
    const price = validPrice(quote?.price);
    const prevClose = validPrice(quote?.prev_close);
    const priceDate = quotePriceDate(quote);

    if (price != null && priceDate && priceDate !== asOfDate) {
        return {
            livePrice: price,
            returnBasePrice: price,
        };
    }

    return {
        livePrice: price ?? prevClose,
        returnBasePrice: prevClose,
    };
};

export const buildCompactLiveLabel = (tickers, snapshot) => {
    if (!tickers?.length) return "";
    const delayNote = " (15m delayed)";

    const updatedTimes = tickers
        .map((ticker) => normalizeTimestampMs(snapshot?.quotes?.[ticker]?.updated))
        .filter((value) => Number.isFinite(value));

    if (updatedTimes.length) {
        const label = formatCompactNyTimestamp(Math.max(...updatedTimes));
        if (label) return `Live: ${label}${delayNote}`;
    }

    if (snapshot?.status === "reconnecting") return `Live: reconnecting${delayNote}`;
    if (snapshot?.status === "connecting") return `Live: connecting${delayNote}`;
    return "";
};
