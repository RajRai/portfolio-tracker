import test from "node:test";
import assert from "node:assert/strict";
import { buildCompactLiveLabel, mergeLiveQuote } from "./liveQuotes.js";

test("buildCompactLiveLabel ignores zero timestamps instead of rendering the unix epoch", () => {
    const label = buildCompactLiveLabel(
        ["SPY"],
        {
            status: "poll",
            quotes: {
                SPY: {
                    updated: 0,
                },
            },
        }
    );

    assert.equal(label, "");
});

test("buildCompactLiveLabel keeps recent live timestamps", () => {
    const updated = Date.now() - 60 * 60 * 1000;
    const label = buildCompactLiveLabel(
        ["SPY"],
        {
            status: "poll",
            quotes: {
                SPY: {
                    updated,
                },
            },
        }
    );

    assert.match(label, /^Live: .+ \(15m delayed\)$/);
});

test("buildCompactLiveLabel falls back to snapshot lastUpdated when per-ticker timestamps are missing", () => {
    const updated = Date.now() - 60 * 60 * 1000;
    const label = buildCompactLiveLabel(
        ["SPY"],
        {
            status: "poll",
            lastUpdated: updated,
            quotes: {
                SPY: {
                    updated: null,
                },
            },
        }
    );

    assert.match(label, /^Live: .+ \(15m delayed\)$/);
});

test("mergeLiveQuote preserves an existing timestamp when a later payload omits it", () => {
    const merged = mergeLiveQuote(
        {
            price: 100,
            updated: 1760000000000,
        },
        {
            price: 101,
        },
        "poll"
    );

    assert.equal(merged.price, 101);
    assert.equal(merged.updated, 1760000000000);
});

test("mergeLiveQuote uses receive time for stream payloads that omit timestamps", () => {
    const merged = mergeLiveQuote(
        {
            price: 100,
        },
        {
            price: 101,
        },
        "stream",
        1760000001234
    );

    assert.equal(merged.price, 101);
    assert.equal(merged.updated, 1760000001234);
});
