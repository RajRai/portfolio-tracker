import React, { useEffect, useState, useSyncExternalStore } from "react";
import Papa from "papaparse";
import { Box, CircularProgress, Typography, Paper, useMediaQuery } from "@mui/material";
import { alpha, useTheme } from "@mui/material/styles";
import { DataGrid } from "@mui/x-data-grid";
import { buildCompactLiveLabel } from "../liveQuotes.js";

const EM_DASH = "\u2014";
const EMPTY_LIVE_SNAPSHOT = { status: "off", message: "", quotes: {} };

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

const formatPct = (value) => (isNaN(value) ? EM_DASH : `${value >= 0 ? "+" : ""}${(value * 100).toFixed(2)}%`);

export default function CSVTable({ src, live = false, liveStore, onHeaderTextChange, fillHeight = false }) {
    const theme = useTheme();
    const isMobile = useMediaQuery(theme.breakpoints.down("sm"));
    const rowHeight = isMobile ? 32 : 40;
    const columnHeaderHeight = isMobile ? 34 : 40;
    const shellBackground =
        theme.palette.mode === "dark"
            ? alpha(theme.palette.common.black, 0.18)
            : alpha(theme.palette.background.paper, 0.98);
    const headerBackground = theme.palette.background.paper;
    const chromeBackground =
        theme.palette.mode === "dark"
            ? alpha(theme.palette.common.black, 0.34)
            : alpha(theme.palette.common.black, 0.035);
    const edgeColor = alpha(theme.palette.divider, theme.palette.mode === "dark" ? 0.24 : 0.14);
    const [rows, setRows] = useState([]);
    const [columns, setColumns] = useState([]);
    const [loading, setLoading] = useState(true);
    const [liveTickers, setLiveTickers] = useState([]);
    const liveSnapshot = useSyncExternalStore(
        liveStore?.subscribe || (() => () => {}),
        liveStore?.getSnapshot || (() => EMPTY_LIVE_SNAPSHOT),
        liveStore?.getSnapshot || (() => EMPTY_LIVE_SNAPSHOT)
    );

    useEffect(() => {
        let cancelled = false;
        setLiveTickers([]);
        setRows([]);
        setColumns([]);
        setLoading(true);

        fetch(src)
            .then((r) => r.text())
            .then((text) => {
                const parsed = Papa.parse(text, { header: true }).data;
                const clean = parsed.filter((row) => row && Object.values(row).some((v) => v?.trim()));
                if (!clean.length) {
                    if (!cancelled) {
                        setLoading(false);
                    }
                    return;
                }

                const headers = Object.keys(clean[0]);
                const visibleHeaders = headers.filter((h) => !h.startsWith("_"));

                const sortComparator = (v1, v2) => {
                    const n1 = toNum(v1);
                    const n2 = toNum(v2);
                    const bothNumeric = !isNaN(n1) && !isNaN(n2);
                    if (bothNumeric) return n1 - n2;
                    return String(v1 || "").localeCompare(String(v2 || ""));
                };

                const cols = visibleHeaders.map((h) => {
                    const sample = clean[0][h];
                    const numeric = isNumericLike(sample);
                    const glColumn = h.includes("G/L");
                    const actionColumn = h === "Action";
                    const dateColumn = h === "Date";
                    const tickerColumn = h === "Ticker";
                    const compactMinWidth = numeric ? 86 : 80;
                    const columnMinWidth = dateColumn
                        ? isMobile ? 90 : 132
                        : tickerColumn && isMobile
                            ? 72
                            : isMobile ? compactMinWidth : 120;

                    return {
                        field: h,
                        headerName: h.replace(/_/g, " "),
                        ...(isMobile && actionColumn
                            ? { width: 64, minWidth: 64, maxWidth: 64 }
                            : { flex: 1, minWidth: columnMinWidth }),
                        sortable: true,
                        align: actionColumn ? "center" : numeric ? "right" : "left",
                        headerAlign: actionColumn ? "center" : numeric ? "right" : "left",
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

                const withIds = clean.map((row, i) => ({ id: i, ...row }));

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
                }
            })
            .catch(() => {
                if (!cancelled) setLoading(false);
            });

        return () => {
            cancelled = true;
        };
    }, [isMobile, live, src]);

    useEffect(() => {
        if (!live || !liveTickers.length) return;
        const asOfDate = nyDateString();
        const hasAnyTradeToday = liveTickers.some((ticker) => {
            const quote = liveSnapshot.quotes?.[ticker];
            const price = toNum(quote?.price);
            return !isNaN(price) && price > 0 && timestampToNyDate(quote?.updated) === asOfDate;
        });

        if (!hasAnyTradeToday) return;

        setRows((prev) =>
            prev.map((row) => {
                const ticker = row.Ticker?.trim();
                const quote = ticker ? liveSnapshot.quotes?.[ticker] : null;
                if (!quote) return row;

                const quantity = toNum(row._Quantity);
                const basisApprox = toNum(row._BasisApprox);
                const price = toNum(quote.price);
                const prevClose = toNum(quote.prev_close);
                const quoteTradedToday =
                    !isNaN(price) && price > 0 && timestampToNyDate(quote.updated) === asOfDate;
                const livePrice = quoteTradedToday ? price : prevClose;
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
    }, [live, liveTickers, liveSnapshot]);

    const headerText = buildCompactLiveLabel(liveTickers, liveSnapshot);

    useEffect(() => {
        if (!onHeaderTextChange) return undefined;
        onHeaderTextChange(headerText);
        return () => {
            onHeaderTextChange("");
        };
    }, [headerText, onHeaderTextChange]);

    if (loading) {
        return (
            <Box sx={{ p: 4, textAlign: "center" }}>
                <CircularProgress />
            </Box>
        );
    }

    if (!rows.length) {
        return (
            <Typography sx={{ mt: 4, textAlign: "center" }}>
                No holdings data available.
            </Typography>
        );
    }

    const fittedTableHeight = columnHeaderHeight + rows.length * rowHeight + 2;

    return (
        <Paper
            sx={{
                width: { xs: "100%", sm: "92%" },
                maxWidth: "100%",
                ...(fillHeight
                    ? { flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }
                    : { height: fittedTableHeight }),
                boxSizing: "border-box",
                mx: "auto",
                mt: { xs: 1, sm: 2 },
                borderRadius: { xs: "12px", sm: "10px" },
                overflow: "hidden",
                backgroundColor: shellBackground,
                border: `1px solid ${edgeColor}`,
                boxShadow: "none",
            }}
            elevation={3}
        >
            <DataGrid
                rows={rows}
                columns={columns}
                disableRowSelectionOnClick
                disableColumnMenu
                hideFooter
                density={isMobile ? "compact" : "standard"}
                rowHeight={rowHeight}
                columnHeaderHeight={columnHeaderHeight}
                pageSizeOptions={[{ value: -1, label: "All" }]}
                initialState={{
                    pagination: { paginationModel: { pageSize: -1, page: 0 } },
                }}
                sx={{
                    minWidth: 0,
                    ...(fillHeight ? { flex: 1 } : { height: "100%" }),
                    border: 0,
                    borderRadius: 0,
                    backgroundColor: "transparent",
                    "--DataGrid-containerBackground": headerBackground,
                    "--DataGrid-pinnedBackground": headerBackground,
                    "--DataGrid-rowBorderColor": edgeColor,
                    "& .MuiDataGrid-filler, & .MuiDataGrid-scrollbarFiller": {
                        backgroundColor: chromeBackground,
                    },
                    "& .MuiDataGrid-columnHeader, & .MuiDataGrid-columnHeaders": {
                        backgroundColor: headerBackground,
                        color: theme.palette.text.primary,
                    },
                    "& .MuiDataGrid-columnHeaders": {
                        fontWeight: 700,
                        borderBottom: `1px solid ${edgeColor}`,
                    },
                    "& .MuiDataGrid-columnSeparator": {
                        opacity: 0.16,
                    },
                    "& .MuiDataGrid-cell, & .MuiDataGrid-columnHeader": {
                        borderColor: edgeColor,
                    },
                    "& .MuiDataGrid-row:hover": {
                        backgroundColor: theme.palette.action.hover,
                    },
                    "& .MuiDataGrid-virtualScroller": {
                        overflowX: "auto",
                    },
                    "& .MuiDataGrid-columnHeader": {
                        px: isMobile ? 0.75 : 1.5,
                    },
                    "& .MuiDataGrid-cell": {
                        px: isMobile ? 0.75 : 1.5,
                        py: isMobile ? 0.25 : 0.5,
                        fontSize: isMobile ? "0.74rem" : "0.875rem",
                    },
                    "& .MuiDataGrid-columnHeaderTitle": {
                        fontSize: isMobile ? "0.72rem" : "0.875rem",
                        fontWeight: 700,
                    },
                    "& .MuiDataGrid-cell.gl-pos": {
                        color: theme.palette.success.main,
                        fontWeight: 600,
                    },
                    "& .MuiDataGrid-cell.gl-neg": {
                        color: theme.palette.error.main,
                        fontWeight: 600,
                    },
                    "& .MuiDataGrid-cell.gl-flat": {
                        color: theme.palette.mode === "dark" ? theme.palette.common.white : theme.palette.text.primary,
                        fontWeight: 600,
                    },
                }}
            />
        </Paper>
    );
}
