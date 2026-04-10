import React, { useEffect, useState, useSyncExternalStore } from "react";
import Papa from "papaparse";
import { Box, CircularProgress, Typography, Paper } from "@mui/material";
import { DataGrid } from "@mui/x-data-grid";

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

const formatPct = (value) => (isNaN(value) ? EM_DASH : `${value >= 0 ? "+" : ""}${(value * 100).toFixed(2)}%`);

export default function CSVTable({ src, live = false, liveStore, onHeaderTextChange }) {
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
    }, [live, src]);

    useEffect(() => {
        if (!live || !liveTickers.length) return;

        setRows((prev) =>
            prev.map((row) => {
                const ticker = row.Ticker?.trim();
                const quote = ticker ? liveSnapshot.quotes?.[ticker] : null;
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
    }, [live, liveTickers, liveSnapshot]);

    const headerText =
        liveTickers.length > 0
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
                        backgroundColor: (theme) => theme.palette.grey[200],
                        fontWeight: 700,
                    },
                    "& .MuiDataGrid-row:hover": {
                        backgroundColor: (theme) => theme.palette.action.hover,
                    },
                    "& .MuiDataGrid-cell.gl-pos": {
                        color: (theme) => theme.palette.success.main,
                        fontWeight: 600,
                    },
                    "& .MuiDataGrid-cell.gl-neg": {
                        color: (theme) => theme.palette.error.main,
                        fontWeight: 600,
                    },
                    "& .MuiDataGrid-cell.gl-flat": {
                        color: (theme) => (theme.palette.mode === "dark" ? theme.palette.common.white : theme.palette.text.primary),
                        fontWeight: 600,
                    },
                }}
            />
        </Paper>
    );
}
