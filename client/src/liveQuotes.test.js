import test from "node:test";
import assert from "node:assert/strict";
import { buildCompactLiveLabel } from "./liveQuotes.js";

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
