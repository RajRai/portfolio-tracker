import React, { useEffect, useState, useRef } from "react";
import {
    Button,
    CircularProgress,
    Typography,
    Stack,
    Divider,
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

export default function PlotlyDashboard({ account }) {
    const theme = useTheme();
    const [data, setData] = useState(null);
    const [range, setRange] = useState("all");
    const [Plotly, setPlotly] = useState(null);

    // Chart refs
    const charts = {
        cum: useRef(null),
        daily: useRef(null),
        spreadDaily: useRef(null),
        spreadCum: useRef(null),
        weights: useRef(null),
    };

    // 🚀 Lazy-load Plotly once
    useEffect(() => {
        let cancelled = false;
        async function loadAll() {
            const [plotlyLib] = await Promise.all([getPlotly()]);
            if (!cancelled) setPlotly(plotlyLib);
        }
        loadAll();
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
    }, [account, Plotly]);

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

        // Cumulative
        makePlot(
            charts.cum,
            [
                {
                    name: "Portfolio",
                    type: "scatter",
                    mode: "lines",
                    x: arrX(payload.portfolio.equity),
                    y: arrY(payload.portfolio.equity).map(v => v - 1), // convert 1.0→0%
                },
                {
                    name: "Benchmark",
                    type: "scatter",
                    mode: "lines",
                    x: arrX(payload.benchmark.equity),
                    y: arrY(payload.benchmark.equity).map(v => v - 1),
                },
            ],
            { yaxis: { tickformat: "+.1%" } }
        );

        // Daily Returns
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

        // Daily Spread
        makePlot(
            charts.spreadDaily,
            [
                {
                    name: "Excess Return",
                    type: "bar",
                    x: arrX(payload.spread.daily),
                    y: arrY(payload.spread.daily),
                    marker: {
                        color: payload.spread.daily.map((p) =>
                            p.v >= 0 ? "#3ac569" : "#e74c3c"
                        ),
                    },
                },
            ],
            { yaxis: { tickformat: "+.2%", title: "Excess Return" } }
        );

        // Cumulative Spread
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

// 🟢 Holdings Over Time — dual-layer, no dates, clean hovers
        const traces = [];

        for (const s of payload.weights) {
            const x = s.points.map((p) => p.t);
            const y = s.points.map((p) => p.v);

            // 1️⃣ Base stacked layer for visuals
            traces.push({
                name: s.name,
                type: "scatter",
                mode: "lines",
                stackgroup: "one",
                line: { width: 1 },
                x,
                y,
                hoverinfo: "skip", // no hover on fill layer
            });

            // 2️⃣ Hover-only overlay (filtered, invisible)
            const xf = [];
            const yf = [];
            for (let i = 0; i < y.length; i++) {
                if (Math.abs(y[i]) >= 0.01) { // show only ≥1%
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
                marker: { size: 6, opacity: 0 }, // invisible hitbox
                line: { width: 0 },
                hovertemplate: "%{y:.1%}<extra>%{fullData.name}</extra>",
                connectgaps: false,
            });
        }

        makePlot(charts.weights, traces, {
            yaxis: { tickformat: ".0%", rangemode: "tozero" },
            hovermode: "x",
        });

        return () => {
            Object.values(charts).forEach((ref) => {
                if (ref.current) Plotly.purge(ref.current);
            });
        };
    }, [data, Plotly, theme]);

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
                (el) =>
                    el && Plotly.relayout(el, { "xaxis.range": [startDate, endDate] })
            );
        }
    };

    if (!account?.report) return null;
    if (!Plotly || !data) return <CircularProgress sx={{ mt: 4 }} />;

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
        <div style={{ width: "100%" }}>
            {/* 🔹 Range Buttons */}
            <Stack
                direction="row"
                spacing={1.5}
                useFlexGap
                flexWrap="wrap"
                sx={{ mb: 3, mt: 1 }}
            >
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

            <div style={{ marginTop: 64 }}>
                <ReportFrame src={account.report} />
            </div>
        </div>
    );
}
