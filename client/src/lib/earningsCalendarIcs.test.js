import test from "node:test";
import assert from "node:assert/strict";
import { buildEarningsCalendarFilename, buildEarningsCalendarIcs } from "./earningsCalendarIcs.js";

test("buildEarningsCalendarIcs creates timed Eastern events for earnings with a time", () => {
    const ics = buildEarningsCalendarIcs(
        [
            {
                ticker: "AAPL",
                company_name: "Apple Inc",
                date: "2026-08-01",
                time: "07:00:00",
                date_status: "estimated",
                provider: "Yahoo Finance",
            },
        ],
        {
            now: new Date("2026-06-17T12:34:56Z"),
        }
    );

    assert.match(ics, /BEGIN:VEVENT/);
    assert.match(ics, /SUMMARY:Earnings: AAPL - Apple Inc/);
    assert.match(ics, /DTSTAMP:20260617T123456Z/);
    assert.match(ics, /DTSTART;TZID=America\/New_York:20260801T070000/);
    assert.match(ics, /DTEND;TZID=America\/New_York:20260801T080000/);
    assert.match(ics, /STATUS:TENTATIVE/);
});

test("buildEarningsCalendarIcs creates all-day events when no time is available", () => {
    const ics = buildEarningsCalendarIcs(
        [
            {
                ticker: "MSFT",
                date: "2026-09-15",
                time: null,
                date_status: "reported",
            },
        ],
        {
            now: new Date("2026-06-17T12:34:56Z"),
        }
    );

    assert.match(ics, /DTSTART;VALUE=DATE:20260915/);
    assert.match(ics, /DTEND;VALUE=DATE:20260916/);
    assert.match(ics, /STATUS:CONFIRMED/);
});

test("buildEarningsCalendarFilename uses the requested range", () => {
    const fileName = buildEarningsCalendarFilename({
        start: "2026-06-17",
        end: "2026-09-15",
    });

    assert.equal(fileName, "earnings-calendar-2026-06-17-to-2026-09-15.ics");
});
