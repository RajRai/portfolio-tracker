import React, { useEffect, useState, memo, useMemo } from "react";
import {
    Button,
    CircularProgress,
    Typography,
    Stack,
    Divider,
    Box,
} from "@mui/material";
import { useTheme } from "@mui/material/styles";
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

// ✅ Memoized performance table with scoped styles (beats MUI overrides)
const PerformanceTable = memo(({ tableData, theme }) => (
    <Box
        className="performance-table"
        sx={{
            overflowX: "auto",
            mb: 3,
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

export default function PlotlyDashboard({ account }) {
    const theme = useTheme();
    const [data, setData] = useState(null);
    const [range, setRange] = useState("all");
    const [Plotly, setPlotly] = useState(null);

    // ✅ stable refs
    const charts = useMemo(
        () => ({
            cum: React.createRef(),
            daily: React.createRef(),
            spreadDaily: React.createRef(),
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

    // 🎨 Build charts once Plotly + data ready
    useEffect(() => {
        if (!data || !Plotly) return;

        const payload = data;
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
        };

        const makePlot = (ref, traces, extraLayout) => {
            if (!ref.current) return;
            Plotly.newPlot(
                ref.current,
                traces,
                { ...baseLayout, ...extraLayout },
                { displayModeBar: false }
            );
        };

        // --- Cumulative Performance (percent-based)
        makePlot(
            charts.cum,
            [
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
            { yaxis: { tickformat: "+.1%" } }
        );

        // --- Daily Returns
        makePlot(
            charts.daily,
            [
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
            { barmode: "group", yaxis: { tickformat: "+.2%" } }
        );

        // --- Daily Spread
        makePlot(
            charts.spreadDaily,
            [
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
            { yaxis: { tickformat: "+.2%", title: "Excess Return" } }
        );

        // --- Cumulative Spread
        makePlot(
            charts.spreadCum,
            [
                {
                    name: "Cumulative Alpha",
                    type: "scatter",
                    mode: "lines",
                    x: arrX(payload.spread.cumulative),
                    y: arrY(payload.spread.cumulative),
                },
            ],
            { yaxis: { tickformat: "+.2%" } }
        );

        // --- Holdings Over Time
        const traces = [];
        for (const s of payload.weights) {
            const x = s.points.map((p) => p.t);
            const y = s.points.map((p) => p.v);

            traces.push({
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

            traces.push({
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

        makePlot(charts.weights, traces, {
            yaxis: { tickformat: ".0%", rangemode: "tozero" },
            hovermode: "x",
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

    const handleSetRange = (r) => {
        setRange(r);
        if (!data || !Plotly) return;
        const ids = Object.values(charts).map((ref) => ref.current);
        const end = lastDate(data);
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
    const eq = data.portfolio.equity || [];
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
                p = oneDayReturn(data.portfolio.daily, data.portfolio.equity);
                b = oneDayReturn(data.benchmark.daily, data.benchmark.equity);
            } else if (label === "YTD") {
                p = ytdReturn(data.portfolio.equity);
                b = ytdReturn(data.benchmark.equity);
            } else if (label === "ALL") {
                p = allTimeReturn(data.portfolio.equity);
                b = allTimeReturn(data.benchmark.equity);
            } else if (typeof span === "number") {
                if (availableDays >= Math.min(span, availableDays)) {
                    p = periodReturn(data.portfolio.equity, span);
                    b = periodReturn(data.benchmark.equity, span);
                }
            }

            const diff = p != null && b != null ? p - b : null;

            const displayLabel =
                label === "ALL"
                    ? (() => {
                        const since = fmtSince(firstDateStr(data.portfolio.equity));
                        return since ? `ALL (since ${since})` : "ALL";
                    })()
                    : label;

            return { label, displayLabel, p, b, diff };
        })
        .filter((row) => row.p != null || row.b != null || row.diff != null);

    const renderSection = (title, ref) => (
        <div style={{ marginBottom: 48 }}>
            <Typography variant="h6" sx={{ mb: 1.5, fontWeight: 500 }}>
                {title}
            </Typography>
            <div ref={ref} style={{ width: "100%", height: 400 }} />
            <Divider sx={{ mt: 4 }} />
        </div>
    );

    return (
        <Box
            sx={{
                width: "100%",
                px: { xs: 1.5, sm: 3 },
                pt: { xs: 2, sm: 3 },
                pb: 6,
            }}
        >
            <Divider sx={{ mb: 3, opacity: 0.4 }} />

            <Box sx={{ mb: 4 }}>
                <PerformanceTable tableData={tableData} theme={theme} />
            </Box>

            <Stack direction="row" spacing={1.5} useFlexGap flexWrap="wrap" sx={{ mb: 4 }}>
                {["1m", "3m", "6m", "1y", "all"].map((r) => (
                    <Button
                        key={r}
                        variant={range === r ? "contained" : "outlined"}
                        color="primary"
                        size="small"
                        onClick={() => handleSetRange(r)}
                        sx={{ minWidth: 64 }}
                    >
                        {r.toUpperCase()}
                    </Button>
                ))}
            </Stack>

            {renderSection("Cumulative Performance vs Benchmark", charts.cum)}
            {renderSection("Daily Returns", charts.daily)}
            {renderSection("Daily Out/Under-Performance", charts.spreadDaily)}
            {renderSection("Cumulative Out/Under-Performance", charts.spreadCum)}
            {renderSection("Holdings Over Time (Weights)", charts.weights)}

            <Box sx={{ mt: 8 }}>
                <ReportFrame src={account.report} />
            </Box>
        </Box>
    );
}
