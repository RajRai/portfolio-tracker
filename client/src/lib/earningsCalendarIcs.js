const ICS_LINE_BREAK = "\r\n";
const DATE_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;
const TIME_PATTERN = /^(\d{2}):(\d{2})(?::(\d{2}))?$/;
const EVENT_DURATION_MS = 60 * 60 * 1000;

const EASTERN_VTIMEZONE = [
    "BEGIN:VTIMEZONE",
    "TZID:America/New_York",
    "X-LIC-LOCATION:America/New_York",
    "BEGIN:DAYLIGHT",
    "TZOFFSETFROM:-0500",
    "TZOFFSETTO:-0400",
    "TZNAME:EDT",
    "DTSTART:19700308T020000",
    "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU",
    "END:DAYLIGHT",
    "BEGIN:STANDARD",
    "TZOFFSETFROM:-0400",
    "TZOFFSETTO:-0500",
    "TZNAME:EST",
    "DTSTART:19701101T020000",
    "RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU",
    "END:STANDARD",
    "END:VTIMEZONE",
];

const parseDateParts = (value) => {
    const match = String(value || "").match(DATE_PATTERN);
    if (!match) return null;
    return {
        year: Number(match[1]),
        month: Number(match[2]),
        day: Number(match[3]),
    };
};

const parseTimeParts = (value) => {
    const match = String(value || "").match(TIME_PATTERN);
    if (!match) return null;
    return {
        hour: Number(match[1]),
        minute: Number(match[2]),
        second: Number(match[3] || "00"),
    };
};

const formatDateValue = ({ year, month, day }) =>
    `${String(year).padStart(4, "0")}${String(month).padStart(2, "0")}${String(day).padStart(2, "0")}`;

const formatTimeValue = ({ hour, minute, second }) =>
    `${String(hour).padStart(2, "0")}${String(minute).padStart(2, "0")}${String(second).padStart(2, "0")}`;

const formatUtcStamp = (value) => {
    const date = value instanceof Date ? value : new Date(value);
    if (Number.isNaN(date.getTime())) return "19700101T000000Z";
    return [
        String(date.getUTCFullYear()).padStart(4, "0"),
        String(date.getUTCMonth() + 1).padStart(2, "0"),
        String(date.getUTCDate()).padStart(2, "0"),
        "T",
        String(date.getUTCHours()).padStart(2, "0"),
        String(date.getUTCMinutes()).padStart(2, "0"),
        String(date.getUTCSeconds()).padStart(2, "0"),
        "Z",
    ].join("");
};

const nextDateValue = (dateText) => {
    const dateParts = parseDateParts(dateText);
    if (!dateParts) return null;
    const date = new Date(Date.UTC(dateParts.year, dateParts.month - 1, dateParts.day));
    date.setUTCDate(date.getUTCDate() + 1);
    return formatDateValue({
        year: date.getUTCFullYear(),
        month: date.getUTCMonth() + 1,
        day: date.getUTCDate(),
    });
};

const addDurationToLocalDateTime = (dateText, timeText, durationMs = EVENT_DURATION_MS) => {
    const dateParts = parseDateParts(dateText);
    const timeParts = parseTimeParts(timeText);
    if (!dateParts || !timeParts) return null;

    const date = new Date(Date.UTC(
        dateParts.year,
        dateParts.month - 1,
        dateParts.day,
        timeParts.hour,
        timeParts.minute,
        timeParts.second
    ));
    date.setTime(date.getTime() + durationMs);

    return {
        dateValue: formatDateValue({
            year: date.getUTCFullYear(),
            month: date.getUTCMonth() + 1,
            day: date.getUTCDate(),
        }),
        timeValue: formatTimeValue({
            hour: date.getUTCHours(),
            minute: date.getUTCMinutes(),
            second: date.getUTCSeconds(),
        }),
    };
};

const escapeIcsText = (value) =>
    String(value || "")
        .replace(/\\/g, "\\\\")
        .replace(/\r?\n/g, "\\n")
        .replace(/;/g, "\\;")
        .replace(/,/g, "\\,");

const foldIcsLine = (line) => {
    const text = String(line || "");
    if (text.length <= 75) return [text];

    const parts = [];
    let remaining = text;
    while (remaining.length > 75) {
        parts.push(remaining.slice(0, 75));
        remaining = ` ${remaining.slice(75)}`;
    }
    parts.push(remaining);
    return parts;
};

const formatMetricValue = (value, style = "number") => {
    if (value == null || Number.isNaN(Number(value))) return null;
    const numericValue = Number(value);
    if (style === "currency") {
        return new Intl.NumberFormat("en-US", {
            style: "currency",
            currency: "USD",
            maximumFractionDigits: 2,
        }).format(numericValue);
    }
    return new Intl.NumberFormat("en-US", {
        maximumFractionDigits: 2,
    }).format(numericValue);
};

const buildEventSummary = (event) => {
    const company = String(event.company_name || "").trim();
    return company
        ? `Earnings: ${event.ticker} - ${company}`
        : `Earnings: ${event.ticker}`;
};

const buildEventDescription = (event) => {
    const lines = [];
    if (event.company_name) lines.push(`Company: ${event.company_name}`);
    lines.push(`Ticker: ${event.ticker}`);
    if (event.date_status) lines.push(`Status: ${event.date_status}`);
    if (event.provider) lines.push(`Provider: ${event.provider}`);

    const fiscalText = [event.fiscal_period, event.fiscal_year].filter(Boolean).join(" ");
    if (fiscalText) lines.push(`Fiscal: ${fiscalText}`);

    const estimatedEps = formatMetricValue(event.estimated_eps);
    if (estimatedEps) lines.push(`EPS estimate: ${estimatedEps}`);

    const actualEps = formatMetricValue(event.actual_eps);
    if (actualEps) lines.push(`EPS actual: ${actualEps}`);

    const estimatedRevenue = formatMetricValue(event.estimated_revenue, "currency");
    if (estimatedRevenue) lines.push(`Revenue estimate: ${estimatedRevenue}`);

    const actualRevenue = formatMetricValue(event.actual_revenue, "currency");
    if (actualRevenue) lines.push(`Revenue actual: ${actualRevenue}`);

    return lines.join("\n");
};

const buildEventUid = (event, index) => {
    const raw = `${event.ticker || "event"}-${event.date || "date"}-${event.time || "all-day"}-${index}`;
    return `${raw.replace(/[^A-Za-z0-9.-]+/g, "-")}@fidelity-portfolio-tracker.local`;
};

const buildEventLines = (event, index, dtstamp) => {
    const dateParts = parseDateParts(event.date);
    if (!dateParts || !event.ticker) return [];

    const startDateValue = formatDateValue(dateParts);
    const timeParts = parseTimeParts(event.time);
    const summary = escapeIcsText(buildEventSummary(event));
    const description = escapeIcsText(buildEventDescription(event));
    const status = String(event.date_status || "").toLowerCase() === "estimated" ? "TENTATIVE" : "CONFIRMED";

    const lines = [
        "BEGIN:VEVENT",
        `UID:${buildEventUid(event, index)}`,
        `DTSTAMP:${dtstamp}`,
        `SUMMARY:${summary}`,
        `STATUS:${status}`,
    ];

    if (description) {
        lines.push(`DESCRIPTION:${description}`);
    }

    if (timeParts) {
        const startTimeValue = formatTimeValue(timeParts);
        const endParts = addDurationToLocalDateTime(event.date, event.time);
        lines.push(`DTSTART;TZID=America/New_York:${startDateValue}T${startTimeValue}`);
        lines.push(`DTEND;TZID=America/New_York:${endParts.dateValue}T${endParts.timeValue}`);
    } else {
        lines.push(`DTSTART;VALUE=DATE:${startDateValue}`);
        lines.push(`DTEND;VALUE=DATE:${nextDateValue(event.date)}`);
    }

    lines.push("END:VEVENT");
    return lines;
};

export const buildEarningsCalendarFilename = (data) => {
    const start = String(data?.start || "earnings").replace(/[^0-9-]/g, "");
    const end = String(data?.end || "calendar").replace(/[^0-9-]/g, "");
    return `earnings-calendar-${start}-to-${end}.ics`;
};

export const buildEarningsCalendarIcs = (events, options = {}) => {
    const rows = Array.isArray(events) ? events : [];
    const calendarName = options.calendarName || "Earnings Calendar";
    const dtstamp = formatUtcStamp(options.now || new Date());

    const lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Fidelity Portfolio Tracker//Earnings Calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        `X-WR-CALNAME:${escapeIcsText(calendarName)}`,
        ...EASTERN_VTIMEZONE,
        ...rows.flatMap((event, index) => buildEventLines(event, index, dtstamp)),
        "END:VCALENDAR",
    ];

    return lines.flatMap(foldIcsLine).join(ICS_LINE_BREAK);
};

export const downloadEarningsCalendarIcs = (events, options = {}) => {
    const ics = buildEarningsCalendarIcs(events, options);
    const blob = new Blob([ics], { type: "text/calendar;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = options.fileName || "earnings-calendar.ics";
    anchor.rel = "noopener";
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
};
