import React, { useEffect, useRef, useState } from "react";
import Papa from "papaparse";
import { Box, CircularProgress, Typography, Paper } from "@mui/material";
import { DataGrid } from "@mui/x-data-grid";

const isNumericLike = (val) => {
    if (val == null) return false;
    const s = String(val).replace(/[,$%]/g, "").trim();
    return s !== "" && !isNaN(Number(s));
};

const toNum = (v) => {
    if (v == null) return NaN;
    const s = String(v).replace(/[,$%]/g, "").trim();
    const n = Number(s);
    return isNaN(n) ? NaN : n;
};

const formatPct = (value) => (isNaN(value) ? "—" : `${value >= 0 ? "+" : ""}${(value * 100).toFixed(2)}%`);

export default function CSVTable({ src, live = false }) {
    const [rows, setRows] = useState([]);
    const [columns, setColumns] = useState([]);
    const [loading, setLoading] = useState(true);
    const [liveStatus, setLiveStatus] = useState("off");
    const [liveMessage, setLiveMessage] = useState("");
    const [liveTickers, setLiveTickers] = useState([]);
    const quotesRef = useRef({});

    useEffect(() => {
        let cancelled = false;
        quotesRef.current = {};
        setLiveStatus(live ? "connecting" : "off");
        setLiveMessage(live ? "Live prices: connecting" : "");
        setLiveTickers([]);
        setRows([]);
        setColumns([]);
        setLoading(true);

        fetch(src)
            .then((r) => r.text())
            .then((text) => {
                const parsed = Papa.parse(text, { header: true }).data;
                const clean = parsed.filter((r) => r && Object.values(r).some((v) => v?.trim()));
                if (!clean.length) {
                    if (!cancelled) {
                        setLoading(false);
                        setLiveStatus("off");
                        setLiveMessage("");
                    }
                    return;
                }

                const headers = Object.keys(clean[0]);
                const visibleHeaders = headers.filter((h) => !h.startsWith("_"));

                // Custom comparator for sorting (handles numbers, $, %, etc)
                const sortComparator = (v1, v2) => {
                    const n1 = toNum(v1);
                    const n2 = toNum(v2);
                    const bothNumeric = !isNaN(n1) && !isNaN(n2);
                    if (bothNumeric) return n1 - n2;
                    // fallback to locale string compare
                    return String(v1 || "").localeCompare(String(v2 || ""));
                };

                // Create columns dynamically
                const cols = visibleHeaders.map((h) => {
                    const sample = clean[0][h];
                    const numeric = isNumericLike(sample);
                    const glColumn = h.includes("G/L");
                    return {
                        field: h,
                        headerName: h.replace(/_/g, " "),
                        flex: 1,
                        minWidth: 120,
                        sortable: true,
                        align: numeric ? "right" : "left",
                        headerAlign: numeric ? "right" : "left",
                        sortComparator,
                        cellClassName: glColumn
                            ? (params) => {
                                const n = toNum(params.value);
                                if (isNaN(n)) return "";
                                if (n > 0) return "gl-pos";
                                if (n < 0) return "gl-neg";
                                return "gl-flat";
                            }
                            : undefined,
                    };
                });

                // Add ID column for DataGrid
                const withIds = clean.map((r, i) => ({ id: i, ...r }));

                if (cancelled) return;

                setColumns(cols);
                setRows(withIds);
                setLoading(false);

                const canStreamLive =
                    live &&
                    visibleHeaders.includes("Ticker") &&
                    headers.includes("_Quantity") &&
                    headers.includes("_BasisApprox");

                if (canStreamLive) {
                    setLiveTickers(
                        clean
                            .map((row) => row.Ticker?.trim())
                            .filter(Boolean)
                    );
                    setLiveStatus("connecting");
                } else {
                    setLiveStatus("off");
                    setLiveMessage("");
                }
            })
            .catch(() => {
                if (!cancelled) {
                    setLoading(false);
                    setLiveStatus("off");
                    setLiveMessage("");
                }
            });

        return () => {
            cancelled = true;
        };
    }, [live, src]);

    useEffect(() => {
        if (!live || !liveTickers.length) return;

        const eventSource = new EventSource(
            `/api/live/stocks/stream?tickers=${encodeURIComponent(liveTickers.join(","))}`
        );

        eventSource.onmessage = (event) => {
            const payload = JSON.parse(event.data);

            if (payload.type === "status") {
                setLiveMessage(payload.message || "");
                if (payload.transport === "stream") {
                    setLiveStatus("stream");
                } else if (payload.transport === "poll") {
                    setLiveStatus("poll");
                } else {
                    setLiveStatus("off");
                }
                return;
            }

            if (!payload.quotes) return;

            if (payload.transport === "stream") {
                setLiveStatus("stream");
            } else if (payload.transport === "poll") {
                setLiveStatus("poll");
            }

            for (const [ticker, quote] of Object.entries(payload.quotes)) {
                quotesRef.current[ticker] = {
                    ...quotesRef.current[ticker],
                    ...quote,
                };
            }

            setRows((prev) =>
                prev.map((row) => {
                    const ticker = row.Ticker?.trim();
                    const quote = ticker ? quotesRef.current[ticker] : null;
                    if (!quote) return row;

                    const quantity = toNum(row._Quantity);
                    const basisApprox = toNum(row._BasisApprox);
                    const price = toNum(quote.price);
                    const prevClose = toNum(quote.prev_close);
                    const livePrice = !isNaN(price) && price > 0 ? price : prevClose;
                    const next = {};

                    if (!isNaN(livePrice) && livePrice > 0 && !isNaN(prevClose) && prevClose !== 0) {
                        next["Today G/L"] = formatPct(livePrice / prevClose - 1);
                    }

                    if (!isNaN(livePrice) && livePrice > 0 && !isNaN(quantity) && !isNaN(basisApprox) && basisApprox !== 0) {
                        next["Total G/L (approx.)"] = formatPct((livePrice * quantity) / basisApprox - 1);
                    }

                    return Object.keys(next).length ? { ...row, ...next } : row;
                })
            );
        };

        eventSource.onerror = () => {
            setLiveStatus((prev) => (prev === "poll" ? prev : "reconnecting"));
            setLiveMessage((prev) => (prev.includes("polling") ? prev : "Live prices: reconnecting"));
        };

        return () => {
            eventSource.close();
        };
    }, [live, liveTickers]);

    if (loading)
        return (
            <Box sx={{ p: 4, textAlign: "center" }}>
                <CircularProgress />
            </Box>
        );

    if (!rows.length)
        return (
            <Typography sx={{ mt: 4, textAlign: "center" }}>
                No holdings data available.
            </Typography>
        );

    return (
        <Paper
            sx={{
                height: "calc(100dvh - 200px)",
                width: "90%",
                mx: "auto",
                mt: 2,
                borderRadius: 2,
                overflow: "hidden",
            }}
            elevation={3}
        >
            {liveTickers.length > 0 && (
                <Box
                    sx={{
                        px: 2,
                        py: 1,
                        borderBottom: (t) => `1px solid ${t.palette.divider}`,
                        backgroundColor: (t) => t.palette.action.hover,
                    }}
                >
                    <Typography variant="caption" sx={{ color: "text.secondary" }}>
                        {liveMessage ||
                            (liveStatus === "reconnecting"
                                ? "Live prices: reconnecting"
                                : liveStatus === "connecting"
                                    ? "Live prices: connecting"
                                    : "")}
                    </Typography>
                </Box>
            )}
            <DataGrid
                rows={rows}
                columns={columns}
                disableRowSelectionOnClick
                pageSizeOptions={[10, 25, 50]}
                initialState={{
                    pagination: { paginationModel: { pageSize: 25, page: 0 } },
                }}
                sx={{
                    "& .MuiDataGrid-columnHeaders": {
                        backgroundColor: (t) => t.palette.grey[200],
                        fontWeight: 700,
                    },
                    "& .MuiDataGrid-row:hover": {
                        backgroundColor: (t) => t.palette.action.hover,
                    },
                    "& .MuiDataGrid-cell.gl-pos": {
                        color: (t) => t.palette.success.main,
                        fontWeight: 600,
                    },
                    "& .MuiDataGrid-cell.gl-neg": {
                        color: (t) => t.palette.error.main,
                        fontWeight: 600,
                    },
                    "& .MuiDataGrid-cell.gl-flat": {
                        color: (t) => (t.palette.mode === "dark" ? t.palette.common.white : t.palette.text.primary),
                        fontWeight: 600,
                    },
                }}
            />
        </Paper>
    );
}
