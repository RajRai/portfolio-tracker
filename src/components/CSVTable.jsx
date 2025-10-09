import React, { useEffect, useState } from "react";
import Papa from "papaparse";
import { Box, CircularProgress, Typography, Paper } from "@mui/material";
import { DataGrid } from "@mui/x-data-grid";

export default function CSVTable({ src }) {
    const [rows, setRows] = useState([]);
    const [columns, setColumns] = useState([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        fetch(src)
            .then((r) => r.text())
            .then((text) => {
                const parsed = Papa.parse(text, { header: true }).data;
                const clean = parsed.filter((r) => r && Object.values(r).some((v) => v?.trim()));
                if (!clean.length) {
                    setLoading(false);
                    return;
                }

                const headers = Object.keys(clean[0]);

                // Helper to detect numeric-like strings
                const isNumericLike = (val) => {
                    if (val == null) return false;
                    const s = String(val).replace(/[,$%]/g, "").trim();
                    return s !== "" && !isNaN(Number(s));
                };

                // Helper to extract numeric value
                const toNum = (v) => {
                    if (v == null) return NaN;
                    const s = String(v).replace(/[,$%]/g, "").trim();
                    const n = Number(s);
                    return isNaN(n) ? NaN : n;
                };

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
                const cols = headers.map((h) => {
                    const sample = clean[0][h];
                    const numeric = isNumericLike(sample);
                    return {
                        field: h,
                        headerName: h.replace(/_/g, " "),
                        flex: 1,
                        minWidth: 120,
                        sortable: true,
                        align: numeric ? "right" : "left",
                        headerAlign: numeric ? "right" : "left",
                        sortComparator,
                    };
                });

                // Add ID column for DataGrid
                const withIds = clean.map((r, i) => ({ id: i, ...r }));

                setColumns(cols);
                setRows(withIds);
                setLoading(false);
            })
            .catch(() => setLoading(false));
    }, [src]);

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
                height: "calc(100vh - 200px)",
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
                        backgroundColor: (t) => t.palette.grey[200],
                        fontWeight: 700,
                    },
                    "& .MuiDataGrid-row:hover": {
                        backgroundColor: (t) => t.palette.action.hover,
                    },
                }}
            />
        </Paper>
    );
}
