import React, { useEffect, useState, memo, useMemo, useSyncExternalStore } from "react";
import {
    Button,
    CircularProgress,
    Typography,
    Stack,
    Divider,
    Box,
} from "@mui/material";
import Papa from "papaparse";
import { alpha, useTheme } from "@mui/material/styles";
import ReportFrame from "./ReportFrame.jsx";

// 🧩 Lazy-import the light Plotly build on demand
let PlotlyModule = null;
async function getPlotly() {
    if (!PlotlyModule) {
        const mod = await import("plotly.js-basic-dist-min");
        PlotlyModule = mod.default || mod;
    }
    return PlotlyModule;
}

const toNum = (v) => {
    if (v == null) return NaN;
    const s = String(v).replace(/[,$%]/g, "").trim();
    const n = Number(s);
    return isNaN(n) ? NaN : n;
};

const nyDateString = () => {
    const parts = new Intl.DateTimeFormat("en-US", {
        timeZone: "America/New_York",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
    }).formatToParts(new Date());
    const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
    return `${values.year}-${values.month}-${values.day}`;
};

const timestampToNyDate = (value) => {
    if (value == null || value === "") return null;
    const raw = Number(value);
    if (!Number.isFinite(raw)) return null;

    const absTs = Math.abs(raw);
    const timestampMs =
        absTs >= 1e17 ? raw / 1e6 :
            absTs >= 1e14 ? raw / 1e3 :
                absTs >= 1e11 ? raw :
                    raw * 1000;

    const date = new Date(timestampMs);
    if (Number.isNaN(date.getTime())) return null;

    const parts = new Intl.DateTimeFormat("en-US", {
        timeZone: "America/New_York",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
    }).formatToParts(date);
    const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
    return `${values.year}-${values.month}-${values.day}`;
};

const EMPTY_LIVE_SNAPSHOT = { status: "off", message: "", quotes: {} };
const DATE_RANGES = ["1m", "3m", "6m", "1y", "all"];

const upsertSeriesPoint = (series, point) => {
    if (!series?.length) return point ? [point] : [];
    const next = series.slice();
    if (next[next.length - 1]?.t === point.t) {
        next[next.length - 1] = point;
    } else {
        next.push(point);
    }
    return next;
};

const rollForwardSeries = (series, asOfDate) => {
    if (!series?.length) return series;
    const next = series.slice();
    const lastDate = next[next.length - 1]?.t;
    if (!lastDate || lastDate >= asOfDate) return next;

    const current = new Date(`${lastDate}T00:00:00`);
    const end = new Date(`${asOfDate}T00:00:00`);
    current.setDate(current.getDate() + 1);

    while (current <= end) {
        next.push({
            t: current.toISOString().slice(0, 10),
            v: next[next.length - 1]?.v ?? null,
        });
        current.setDate(current.getDate() + 1);
    }
    return next;
};

const carryLatestPointToDate = (series, asOfDate) => {
    if (!series?.length) return series;
    const lastDate = series[series.length - 1]?.t;
    if (!lastDate || lastDate >= asOfDate) return series.slice();

    const next = series.slice(0, -1);
    const current = new Date(`${lastDate}T00:00:00`);
    const end = new Date(`${asOfDate}T00:00:00`);
    const lastValue = series[series.length - 1]?.v ?? null;
    current.setDate(current.getDate() + 1);

    while (current <= end) {
        next.push({
            t: current.toISOString().slice(0, 10),
            v: lastValue,
        });
        current.setDate(current.getDate() + 1);
    }
    return next;
};

const rollForwardWeights = (weightsSeries, asOfDate) => {
    if (!weightsSeries?.length) return weightsSeries;
    return weightsSeries.map((series) => ({
        ...series,
        points: rollForwardSeries(series.points, asOfDate),
    }));
};

const withLiveEquity = (equitySeries, liveReturn, asOfDate) => {
    if (!equitySeries?.length || liveReturn == null) return equitySeries;
    const next = equitySeries.slice();
    const baseIdx = next[next.length - 1]?.t === asOfDate ? next.length - 2 : next.length - 1;
    const basePoint = next[Math.max(baseIdx, 0)];
    if (!basePoint?.v) return equitySeries;

    const livePoint = {
        t: asOfDate,
        v: basePoint.v * (1 + liveReturn),
    };
    return upsertSeriesPoint(next, livePoint);
};

const withLiveCompoundedReturn = (series, liveReturn, asOfDate) => {
    if (!series?.length || liveReturn == null) return series;
    const next = series.slice();
    const baseIdx = next[next.length - 1]?.t === asOfDate ? next.length - 2 : next.length - 1;
    const basePoint = next[Math.max(baseIdx, 0)];
    if (basePoint?.v == null) return series;

    const livePoint = {
        t: asOfDate,
        v: (1 + basePoint.v) * (1 + liveReturn) - 1,
    };
    return upsertSeriesPoint(next, livePoint);
};

const clampForMultiple = (value) => {
    if (value == null) return value;
    if (value < 0 && value > -0.001) return -0.001;
    if (value >= 0 && value < 0.001) return 0.001;
    return value;
};

const withLiveWeights = (weightsSeries, liveInputs, quotes, asOfDate) => {
    if (!weightsSeries?.length || !liveInputs?.holdings?.length) return weightsSeries;

    const liveValueByTicker = {};
    let totalValue = 0;

    for (const holding of liveInputs.holdings) {
        const quote = quotes[holding.ticker];
        const prevClose = toNum(quote?.prev_close);
        const price = toNum(quote?.price);
        const quoteTradedToday =
            !isNaN(price) && price > 0 && timestampToNyDate(quote?.updated) === asOfDate;
        const livePrice = quoteTradedToday ? price : prevClose;
        if (isNaN(livePrice) || livePrice <= 0) continue;

        const liveValue = holding.quantity * livePrice;
        liveValueByTicker[holding.ticker] = liveValue;
        totalValue += liveValue;
    }

    if (totalValue <= 0) return weightsSeries;

    return weightsSeries.map((series) => ({
        ...series,
        points: upsertSeriesPoint(series.points, {
            t: asOfDate,
            v: (liveValueByTicker[series.name] || 0) / totalValue,
        }),
    }));
};

const withLivePerformance = (payload, liveReturns, liveInputs, quotes) => {
    if (!payload || !liveReturns?.asOfDate) return payload;

    const next = {
        ...payload,
        portfolio: { ...payload.portfolio },
        benchmark: { ...payload.benchmark },
        spread: { ...payload.spread },
        multiple: { ...payload.multiple },
    };

    if (liveReturns.portfolioReturn != null) {
        if (liveReturns.portfolioHasTradeToday) {
            next.portfolio.daily = upsertSeriesPoint(payload.portfolio.daily, {
                t: liveReturns.asOfDate,
                v: liveReturns.portfolioReturn,
            });
            next.portfolio.equity = withLiveEquity(
                payload.portfolio.equity,
                liveReturns.portfolioReturn,
                liveReturns.asOfDate
            );
        } else {
            next.portfolio.daily = carryLatestPointToDate(payload.portfolio.daily, liveReturns.asOfDate);
            next.portfolio.equity = rollForwardSeries(payload.portfolio.equity, liveReturns.asOfDate);
        }
    } else {
        next.portfolio.daily = carryLatestPointToDate(payload.portfolio.daily, liveReturns.asOfDate);
        next.portfolio.equity = rollForwardSeries(payload.portfolio.equity, liveReturns.asOfDate);
    }

    if (liveReturns.benchmarkReturn != null) {
        if (liveReturns.benchmarkHasTradeToday) {
            next.benchmark.daily = upsertSeriesPoint(payload.benchmark.daily, {
                t: liveReturns.asOfDate,
                v: liveReturns.benchmarkReturn,
            });
            next.benchmark.equity = withLiveEquity(
                payload.benchmark.equity,
                liveReturns.benchmarkReturn,
                liveReturns.asOfDate
            );
        } else {
            next.benchmark.daily = carryLatestPointToDate(payload.benchmark.daily, liveReturns.asOfDate);
            next.benchmark.equity = rollForwardSeries(payload.benchmark.equity, liveReturns.asOfDate);
        }
    }

    if (liveReturns.portfolioReturn != null && liveReturns.benchmarkReturn != null) {
        const liveSpread = liveReturns.portfolioReturn - liveReturns.benchmarkReturn;
        if (liveReturns.portfolioHasTradeToday || liveReturns.benchmarkHasTradeToday) {
            next.spread.daily = upsertSeriesPoint(payload.spread.daily, {
                t: liveReturns.asOfDate,
                v: liveSpread,
            });
            next.spread.cumulative = withLiveCompoundedReturn(
                payload.spread.cumulative,
                liveSpread,
                liveReturns.asOfDate
            );
            next.multiple.daily = upsertSeriesPoint(payload.multiple.daily, {
                t: liveReturns.asOfDate,
                v: clampForMultiple(liveReturns.portfolioReturn) / clampForMultiple(liveReturns.benchmarkReturn),
            });
        } else {
            next.spread.daily = carryLatestPointToDate(payload.spread.daily, liveReturns.asOfDate);
            next.spread.cumulative = rollForwardSeries(payload.spread.cumulative, liveReturns.asOfDate);
            next.multiple.daily = carryLatestPointToDate(payload.multiple.daily, liveReturns.asOfDate);
        }
    }

    next.weights = liveReturns.portfolioHasTradeToday
        ? withLiveWeights(
            payload.weights,
            liveInputs,
            quotes,
            liveReturns.asOfDate
        )
        : rollForwardWeights(payload.weights, liveReturns.asOfDate);

    return next;
};

// ✅ Memoized performance table with scoped styles (beats MUI overrides)
const PerformanceTable = memo(({ tableData, theme }) => (
    <Box
        className="performance-table"
        sx={{
            overflowX: "auto",
            borderRadius: 1.5,
            boxShadow: "0px 1px 3px rgba(0,0,0,0.15)",
            bgcolor: theme.palette.background.paper,
            position: "relative",
            display: "inline-block",
            width: "100%",
            marginBottom: 0,
        }}
    >
        <style>{`
      .performance-table table {
        width: 100%;
        border-collapse: collapse;
        text-align: center;
        table-layout: fixed;           /* key: prevents columns from expanding */
        border-radius: 8px;
        overflow: hidden;
        background: ${theme.palette.background.paper};
      }

      .performance-table thead tr {
        background: ${theme.palette.action.hover};
      }

      .performance-table th,
      .performance-table td {
        padding: 8px 10px;             /* tighter than 10/12 */
        border-bottom: 1px solid ${theme.palette.divider};
        color: inherit !important;
        transition: color 0.25s ease;
        white-space: nowrap;           /* key: keeps numbers compact */
        font-variant-numeric: tabular-nums;
        overflow: hidden;              /* key: prevent forcing horizontal scroll */
        text-overflow: ellipsis;
      }

      /* Make headers less chunky without killing alignment */
      .performance-table th {
        font-weight: 600;
      }

      /* remove last-row divider and ghost gap */
      .performance-table tbody tr:last-child td {
        border-bottom: none;
      }

      .performance-table td.gain {
        color: ${theme.palette.success.light} !important;
      }
      .performance-table td.loss {
        color: ${theme.palette.error.light} !important;
      }
      .performance-table td.excess-pos {
        color: ${theme.palette.success.main} !important;
        font-weight: 600;
      }
      .performance-table td.excess-neg {
        color: ${theme.palette.error.main} !important;
        font-weight: 600;
      }
      .performance-table td.excess-flat {
        color: ${theme.palette.text.primary} !important;
        font-weight: 600;
      }

      /* ✅ Mobile density: shrink font + padding */
      @media (max-width: 600px) {
        .performance-table table {
          font-size: 0.82rem;
        }
        .performance-table th,
        .performance-table td {
          padding: 6px 6px;
        }
      }

      @media (max-width: 420px) {
        .performance-table table {
          font-size: 0.76rem;
        }
        .performance-table th,
        .performance-table td {
          padding: 5px 4px;
        }
      }
    `}</style>

        <table style={{ marginBottom: 0 }}>
            <thead>
            <tr>
                <th>Period</th>
                <th>Portfolio</th>
                <th>Benchmark</th>
                <th>Excess</th>
            </tr>
            </thead>
            <tbody>
            {tableData.map(({ label, displayLabel, p, b, diff }) => (
                <tr key={label}>
                    <td style={{ fontWeight: 500, whiteSpace: "nowrap" }}>{displayLabel || label}</td>
                    <td className={p == null ? "" : p > 0 ? "gain" : "loss"}>
                        {p != null ? (p * 100).toFixed(1) + "%" : "—"}
                    </td>
                    <td className={b == null ? "" : b > 0 ? "gain" : "loss"}>
                        {b != null ? (b * 100).toFixed(1) + "%" : "—"}
                    </td>
                    <td
                        className={
                            diff == null
                                ? ""
                                : diff > 0
                                    ? "excess-pos"
                                    : diff < 0
                                        ? "excess-neg"
                                        : "excess-flat"
                        }
                    >
                        {diff != null
                            ? (diff > 0 ? "+" : "") + (diff * 100).toFixed(1) + "%"
                            : "—"}
                    </td>
                </tr>
            ))}
            </tbody>
        </table>
    </Box>
));

const RangeSelector = memo(({ range, onChange, theme }) => (
    <Stack
        direction="row"
        spacing={0.5}
        useFlexGap
        flexWrap="wrap"
        sx={{ mt: 1.25, justifyContent: { xs: "flex-start", sm: "flex-end" } }}
    >
        {DATE_RANGES.map((r) => {
            const active = range === r;
            return (
                <Button
                    key={r}
                    variant="text"
                    color="inherit"
                    size="small"
                    onClick={() => onChange(r)}
                    sx={{
                        minWidth: 0,
                        px: 0.85,
                        py: 0.15,
                        minHeight: 24,
                        borderRadius: 1,
                        fontSize: "0.72rem",
                        fontWeight: active ? 700 : 500,
                        letterSpacing: "0.03em",
                        textTransform: "uppercase",
                        color: active ? theme.palette.primary.main : theme.palette.text.secondary,
                        backgroundColor: active ? alpha(theme.palette.primary.main, 0.16) : "transparent",
                        "&:hover": {
                            backgroundColor: active
                                ? alpha(theme.palette.primary.main, 0.22)
                                : alpha(theme.palette.text.primary, 0.06),
                        },
                    }}
                >
                    {r}
                </Button>
            );
        })}
    </Stack>
));

export default function PlotlyDashboard({ account, liveStore, onHeaderTextChange }) {
    const theme = useTheme();
    const [data, setData] = useState(null);
    const [range, setRange] = useState("all");
    const [Plotly, setPlotly] = useState(null);
    const [liveInputs, setLiveInputs] = useState(null);
    const liveSnapshot = useSyncExternalStore(
        liveStore?.subscribe || (() => () => {}),
        liveStore?.getSnapshot || (() => EMPTY_LIVE_SNAPSHOT),
        liveStore?.getSnapshot || (() => EMPTY_LIVE_SNAPSHOT)
    );

    // ✅ stable refs
    const charts = useMemo(
        () => ({
            cum: React.createRef(),
            daily: React.createRef(),
            spreadDaily: React.createRef(),
            multipleDaily: React.createRef(),
            spreadCum: React.createRef(),
            weights: React.createRef(),
        }),
        []
    );

    // 🚀 Lazy-load Plotly once
    useEffect(() => {
        let cancelled = false;
        (async () => {
            const [plotlyLib] = await Promise.all([getPlotly()]);
            if (!cancelled) setPlotly(plotlyLib);
        })();
        return () => {
            cancelled = true;
        };
    }, []);

    // 🔁 Fetch data whenever account changes
    useEffect(() => {
        if (!account?.report) return;
        let cancelled = false;
        setLiveInputs(null);

        const url = account.report.replace(".html", "_interactive.json");
        fetch(url)
            .then((r) => r.json())
            .then((json) => {
                if (!cancelled) setData(json);
            })
            .catch(console.error);

        return () => {
            cancelled = true;
            Object.values(charts).forEach((ref) => {
                if (ref.current && Plotly) Plotly.purge(ref.current);
            });
        };
    }, [account, Plotly, charts]);

    useEffect(() => {
        if (!account?.weights || !data) return;
        let cancelled = false;

        fetch(account.weights)
            .then((r) => r.text())
            .then((text) => {
                const parsed = Papa.parse(text, { header: true }).data;
                const clean = parsed.filter((row) => row && Object.values(row).some((v) => v?.trim()));
                if (!clean.length || cancelled) return;

                const holdings = clean
                    .map((row) => ({
                        ticker: row.Ticker?.trim(),
                        quantity: toNum(row._Quantity),
                    }))
                    .filter((row) => row.ticker && !isNaN(row.quantity) && row.quantity > 0);

                if (!holdings.length) return;

                const benchmarkTicker = data.benchmark?.ticker || "SPY";
                const tickers = [...new Set([...holdings.map((row) => row.ticker), benchmarkTicker])];

                if (!cancelled) {
                    setLiveInputs({ holdings, benchmarkTicker, tickers });
                }
            })
            .catch(() => {
                if (!cancelled) setLiveInputs(null);
            });

        return () => {
            cancelled = true;
        };
    }, [account?.weights, data]);

    const liveReturns = useMemo(() => {
        if (!liveInputs?.tickers?.length) return null;

        const asOfDate = nyDateString();
        let prevCloseValue = 0;
        let liveValue = 0;
        let hasPortfolioTradeToday = false;

        for (const holding of liveInputs.holdings) {
            const quote = liveSnapshot.quotes?.[holding.ticker];
            const prevClose = toNum(quote?.prev_close);
            const price = toNum(quote?.price);
            if (isNaN(prevClose) || prevClose <= 0) continue;
            const quoteTradedToday =
                !isNaN(price) && price > 0 && timestampToNyDate(quote?.updated) === asOfDate;
            const livePrice = quoteTradedToday ? price : prevClose;

            prevCloseValue += holding.quantity * prevClose;
            liveValue += holding.quantity * livePrice;
            if (quoteTradedToday) {
                hasPortfolioTradeToday = true;
            }
        }

        const benchmarkQuote = liveSnapshot.quotes?.[liveInputs.benchmarkTicker];
        const benchmarkPrevClose = toNum(benchmarkQuote?.prev_close);
        const benchmarkPrice = toNum(benchmarkQuote?.price);
        const benchmarkHasTradeToday =
            !isNaN(benchmarkPrice) && benchmarkPrice > 0 && timestampToNyDate(benchmarkQuote?.updated) === asOfDate;
        const benchmarkLivePrice = benchmarkHasTradeToday ? benchmarkPrice : benchmarkPrevClose;

        const portfolioReturn = prevCloseValue > 0 ? liveValue / prevCloseValue - 1 : null;
        const benchmarkReturn =
            !isNaN(benchmarkPrevClose) && benchmarkPrevClose > 0 && !isNaN(benchmarkLivePrice)
                ? benchmarkLivePrice / benchmarkPrevClose - 1
                : null;

        return {
            asOfDate,
            portfolioReturn,
            benchmarkReturn,
            portfolioHasTradeToday: hasPortfolioTradeToday,
            benchmarkHasTradeToday,
        };
    }, [liveInputs, liveSnapshot]);

    // ✅ MINIMAL CHANGE: resize Plotly charts on window size changes
    useEffect(() => {
        if (!Plotly) return;

        let raf = 0;
        const onResize = () => {
            cancelAnimationFrame(raf);
            raf = requestAnimationFrame(() => {
                Object.values(charts).forEach((ref) => {
                    if (ref.current) Plotly.Plots.resize(ref.current);
                });
            });
        };

        window.addEventListener("resize", onResize);
        return () => {
            window.removeEventListener("resize", onResize);
            cancelAnimationFrame(raf);
        };
    }, [Plotly, charts]);

    const displayData = useMemo(
        () => withLivePerformance(data, liveReturns, liveInputs, liveSnapshot.quotes),
        [data, liveReturns, liveInputs, liveSnapshot]
    );
    const headerText =
        liveInputs?.tickers?.length > 0
            ? liveSnapshot.message ||
                (liveSnapshot.status === "reconnecting"
                    ? "Live prices: reconnecting"
                    : liveSnapshot.status === "connecting"
                        ? "Live prices: connecting"
                        : "")
            : "";

    useEffect(() => {
        if (!onHeaderTextChange) return undefined;
        onHeaderTextChange(headerText);
        return () => {
            onHeaderTextChange("");
        };
    }, [headerText, onHeaderTextChange]);

    const dateMinusDays = (d, n) => {
        const dt = new Date(d);
        dt.setDate(dt.getDate() - n);
        return dt;
    };

    const lastDate = (payload) => {
        const pools = [];
        if (payload.portfolio.equity.length) pools.push(payload.portfolio.equity);
        if (payload.benchmark.equity.length) pools.push(payload.benchmark.equity);
        if (!pools.length) return null;
        return pools[0][pools[0].length - 1].t;
    };

    const rangeToDays = (r) => ({ "1m": 30, "3m": 90, "6m": 180, "1y": 365 }[r] || 0);

    const buildChartSpecs = (payload) => {
        const arrX = (p) => p.map((v) => v.t);
        const arrY = (p) => p.map((v) => v.v);
        const baseLayout = {
            paper_bgcolor: theme.palette.background.paper,
            plot_bgcolor: theme.palette.background.paper,
            font: {
                color: theme.palette.text.primary,
                family: theme.typography.fontFamily,
            },
            legend: { orientation: "h", xanchor: "center", x: 0.5 },
            margin: { l: 48, r: 16, t: 24, b: 48 },
            xaxis: { rangeslider: { visible: true }, automargin: true },
            uirevision: "dashboard",
        };

        const multipleDaily = payload.multiple.daily;
        const portfolioDailyByDate = Object.fromEntries(
            payload.portfolio.daily.map((point) => [point.t, point.v])
        );

        const weightsTraces = [];
        for (const s of payload.weights) {
            const x = s.points.map((p) => p.t);
            const y = s.points.map((p) => p.v);

            weightsTraces.push({
                name: s.name,
                type: "scatter",
                mode: "lines",
                stackgroup: "one",
                line: { width: 1 },
                x,
                y,
                hoverinfo: "skip",
            });

            const xf = [];
            const yf = [];
            for (let i = 0; i < y.length; i++) {
                if (Math.abs(y[i]) >= 0.01) {
                    xf.push(x[i]);
                    yf.push(y[i]);
                }
            }

            weightsTraces.push({
                name: s.name,
                type: "scatter",
                mode: "markers",
                x: xf,
                y: yf,
                marker: { size: 6, opacity: 0 },
                line: { width: 0 },
                hovertemplate: "%{y:.1%}<extra>%{fullData.name}</extra>",
                connectgaps: false,
            });
        }

        return {
            cum: {
                traces: [
                    {
                        name: "Portfolio",
                        type: "scatter",
                        mode: "lines",
                        x: arrX(payload.portfolio.equity),
                        y: arrY(payload.portfolio.equity).map((v) => v - 1),
                    },
                    {
                        name: "Benchmark",
                        type: "scatter",
                        mode: "lines",
                        x: arrX(payload.benchmark.equity),
                        y: arrY(payload.benchmark.equity).map((v) => v - 1),
                    },
                ],
                layout: { ...baseLayout, yaxis: { tickformat: "+.1%" } },
            },
            daily: {
                traces: [
                    {
                        name: "Portfolio",
                        type: "bar",
                        x: arrX(payload.portfolio.daily),
                        y: arrY(payload.portfolio.daily),
                    },
                    {
                        name: "Benchmark",
                        type: "bar",
                        x: arrX(payload.benchmark.daily),
                        y: arrY(payload.benchmark.daily),
                    },
                ],
                layout: { ...baseLayout, barmode: "group", yaxis: { tickformat: "+.2%" } },
            },
            spreadDaily: {
                traces: [
                    {
                        name: "Excess Return",
                        type: "bar",
                        x: arrX(payload.spread.daily),
                        y: arrY(payload.spread.daily),
                        marker: {
                            color: payload.spread.daily.map((p) => (p.v >= 0 ? "#3ac569" : "#e74c3c")),
                        },
                    },
                ],
                layout: { ...baseLayout, yaxis: { tickformat: "+.2%", title: "Excess Return" } },
            },
            multipleDaily: {
                traces: [
                    {
                        name: "Return Multiple",
                        type: "bar",
                        x: arrX(multipleDaily),
                        y: arrY(multipleDaily),
                        marker: {
                            color: multipleDaily.map((p) => (portfolioDailyByDate[p.t] > 0 ? "#3ac569" : "#e74c3c")),
                        },
                    },
                ],
                layout: { ...baseLayout, yaxis: { tickformat: "+.2f", title: "Return Multiple" } },
            },
            spreadCum: {
                traces: [
                    {
                        name: "Cumulative Alpha",
                        type: "scatter",
                        mode: "lines",
                        x: arrX(payload.spread.cumulative),
                        y: arrY(payload.spread.cumulative),
                    },
                ],
                layout: { ...baseLayout, yaxis: { tickformat: "+.2%" } },
            },
            weights: {
                traces: weightsTraces,
                layout: { ...baseLayout, yaxis: { tickformat: ".0%", rangemode: "tozero" }, hovermode: "x" },
            },
        };
    };

    // 🎨 Build charts once Plotly + data ready
    useEffect(() => {
        if (!data || !Plotly) return;

        const specs = buildChartSpecs(data);
        Object.entries(specs).forEach(([key, spec]) => {
            const ref = charts[key];
            if (!ref?.current) return;
            Plotly.newPlot(ref.current, spec.traces, spec.layout, { displayModeBar: false });
        });

        // After initial render, do a resize pass once layout has settled
        requestAnimationFrame(() => {
            Object.values(charts).forEach((ref) => {
                if (ref.current) Plotly.Plots.resize(ref.current);
            });
        });

        return () => {
            Object.values(charts).forEach((ref) => {
                if (ref.current) Plotly.purge(ref.current);
            });
        };
    }, [data, Plotly, theme, charts]);

    useEffect(() => {
        if (!liveReturns || !displayData || !Plotly) return;

        const specs = buildChartSpecs(displayData);
        Object.entries(specs).forEach(([key, spec]) => {
            const ref = charts[key];
            if (!ref?.current) return;
            Plotly.react(ref.current, spec.traces, spec.layout, { displayModeBar: false });
        });
    }, [displayData, liveReturns, Plotly, theme, charts]);

    const handleSetRange = (r) => {
        setRange(r);
        if (!displayData || !Plotly) return;
        const ids = Object.values(charts).map((ref) => ref.current);
        const end = lastDate(displayData);
        if (r === "all" || !end) {
            ids.forEach((el) => el && Plotly.relayout(el, { "xaxis.autorange": true }));
        } else {
            const endDate = new Date(end);
            const startDate = dateMinusDays(endDate, rangeToDays(r));
            ids.forEach(
                (el) => el && Plotly.relayout(el, { "xaxis.range": [startDate, endDate] })
            );
        }
    };

    if (!account?.report) return null;
    if (!Plotly || !data) return <CircularProgress sx={{ mt: 4 }} />;

    // --- 📈 Robust performance comparison helpers ---
    const ms = (d) => (d instanceof Date ? d.getTime() : new Date(d).getTime());

    const fmtSince = (isoDateStr) => {
        if (!isoDateStr) return "";
        const d = new Date(isoDateStr);
        if (Number.isNaN(d.getTime())) return "";
        return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "2-digit" });
    };

    const firstDateStr = (series) => (series?.length ? series[0]?.t : null);

    // Find index at-or-before a cutoff date
    const idxAtOrBefore = (series, cutoffMs) => {
        let lo = 0,
            hi = series.length - 1,
            ans = -1;
        while (lo <= hi) {
            const mid = (lo + hi) >> 1;
            if (ms(series[mid].t) <= cutoffMs) {
                ans = mid;
                lo = mid + 1;
            } else {
                hi = mid - 1;
            }
        }
        return ans; // -1 means no point on/before
    };

    // First index on-or-after a date
    const idxOnOrAfter = (series, targetMs) => {
        let lo = 0,
            hi = series.length - 1,
            ans = series.length;
        while (lo <= hi) {
            const mid = (lo + hi) >> 1;
            if (ms(series[mid].t) >= targetMs) {
                ans = mid;
                hi = mid - 1;
            } else {
                lo = mid + 1;
            }
        }
        return ans === series.length ? -1 : ans;
    };

    // Period return using equity series (calendar days), from value at-or-before cutoff to last
    const periodReturn = (series, calendarDays) => {
        if (!series?.length) return null;
        const endIdx = series.length - 1;
        const endMs = ms(series[endIdx].t);
        const cutoff = new Date(endMs);
        cutoff.setDate(cutoff.getDate() - calendarDays);
        const startIdx = idxAtOrBefore(series, cutoff.getTime());
        if (startIdx < 0) return null;
        const start = series[startIdx].v;
        const end = series[endIdx].v;
        if (start === 0 || start == null || end == null) return null;
        return end / start - 1;
    };

    // YTD return from Jan 1 of last equity year (first trading day of that year)
    const ytdReturn = (series) => {
        if (!series?.length) return null;
        const endIdx = series.length - 1;
        const endDate = new Date(series[endIdx].t);
        const jan1 = new Date(endDate.getFullYear(), 0, 1);
        const startIdx = idxOnOrAfter(series, jan1.getTime());
        if (startIdx < 0) return null;
        const start = series[startIdx].v;
        const end = series[endIdx].v;
        if (start === 0 || start == null || end == null) return null;
        return end / start - 1;
    };

    // 1D return: prefer last daily return, else fall back to equity one-day ratio
    const oneDayReturn = (dailySeries, equitySeries) => {
        if (dailySeries?.length) {
            const last = dailySeries[dailySeries.length - 1].v;
            if (typeof last === "number") return last;
        }
        return periodReturn(equitySeries, 1);
    };

    // All-time return from first equity point to last
    const allTimeReturn = (series) => {
        if (!series?.length) return null;
        const start = series[0]?.v;
        const end = series[series.length - 1]?.v;
        if (start == null || end == null || start === 0) return null;
        return end / start - 1;
    };

    // Build timeframes with YTD inserted in the “correct” position
    const eq = displayData.portfolio.equity || [];
    const availableDays = (() => {
        if (eq.length < 2) return 0;
        const start = new Date(eq[0].t);
        const end = new Date(eq[eq.length - 1].t);
        return Math.floor((end - start) / (1000 * 60 * 60 * 24));
    })();

    const lastEqDate = (() => (eq.length ? new Date(eq[eq.length - 1].t) : null))();

    const ytdDays = (() => {
        if (!lastEqDate) return null;
        const jan1 = new Date(lastEqDate.getFullYear(), 0, 1);
        const days = Math.floor((lastEqDate - jan1) / (1000 * 60 * 60 * 24));
        return Math.max(0, days);
    })();

    // “Fixed” windows (exclude YTD; we’ll insert it)
    const fixedTimeframes = [
        ["1D", "1D"],
        ["7D", 7],
        ["30D", 30],
        ["3M", 90],
        ["6M", 180],
        ["1Y", 365],
        ["3Y", 365 * 3],
        ["5Y", 365 * 5],
        ["10Y", 365 * 10],
        ["ALL", "ALL"],
    ];

    // Insert YTD right after the largest fixed window <= ytdDays (or after 1D if early year)
    const timeframes = (() => {
        if (ytdDays == null) return fixedTimeframes;

        // Find insertion index (after last numeric span <= ytdDays, but keep 1D first)
        let insertAt = 1; // default: after 1D
        for (let i = 0; i < fixedTimeframes.length; i++) {
            const [, span] = fixedTimeframes[i];
            if (typeof span === "number" && span <= ytdDays) {
                insertAt = i + 1;
            }
        }

        const out = fixedTimeframes.slice();
        out.splice(insertAt, 0, ["YTD", "YTD"]);
        return out;
    })();

    // Compute table data
    const tableData = timeframes
        .map(([label, span]) => {
            let p = null, b = null;

            if (label === "1D") {
                p = oneDayReturn(displayData.portfolio.daily, displayData.portfolio.equity);
                b = oneDayReturn(displayData.benchmark.daily, displayData.benchmark.equity);
            } else if (label === "YTD") {
                p = ytdReturn(displayData.portfolio.equity);
                b = ytdReturn(displayData.benchmark.equity);
            } else if (label === "ALL") {
                p = allTimeReturn(displayData.portfolio.equity);
                b = allTimeReturn(displayData.benchmark.equity);
            } else if (typeof span === "number") {
                if (availableDays >= Math.min(span, availableDays)) {
                    p = periodReturn(displayData.portfolio.equity, span);
                    b = periodReturn(displayData.benchmark.equity, span);
                }
            }

            const diff = p != null && b != null ? p - b : null;

            const displayLabel = label;

            return { label, displayLabel, p, b, diff };
        })
        .filter((row) => row.p != null || row.b != null || row.diff != null);

    const renderSection = (title, ref) => (
        <div style={{ marginBottom: 48 }}>
            <Typography variant="h6" sx={{ mb: 1.5, fontWeight: 500 }}>
                {title}
            </Typography>
            <div ref={ref} style={{ width: "100%", height: 400 }} />
            <RangeSelector range={range} onChange={handleSetRange} theme={theme} />
            <Divider sx={{ mt: 4 }} />
        </div>
    );

    return (
        <Box
            sx={{
                width: "100%",
                px: { xs: 1.5, sm: 3 },
                pt: { xs: 0.5, sm: 1 },
                pb: 6,
            }}
        >
            <Box sx={{ mb: 0.75 }}>
                <PerformanceTable tableData={tableData} theme={theme} />
            </Box>

            {renderSection("Cumulative Performance vs Benchmark", charts.cum)}
            {renderSection("Daily Returns", charts.daily)}
            {renderSection("Daily Out/Under-Performance", charts.spreadDaily)}
            {renderSection("Daily Return Multiple vs Market", charts.multipleDaily)}
            {renderSection("Cumulative Out/Under-Performance", charts.spreadCum)}
            {renderSection("Holdings Over Time (Weights)", charts.weights)}

            <Box sx={{ mt: 8 }}>
                <ReportFrame src={account.report} />
            </Box>
        </Box>
    );
}
