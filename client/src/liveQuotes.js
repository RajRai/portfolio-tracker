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
