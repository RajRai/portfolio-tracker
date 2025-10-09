import React, { useEffect, useState } from "react";
import Papa from "papaparse";
import {
    Table,
    TableHead,
    TableBody,
    TableCell,
    TableRow,
    Paper,
    TableContainer,
    CircularProgress,
    Typography,
    Box,
} from "@mui/material";

export default function HoldingsTable({ src }) {
    const [data, setData] = useState([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        fetch(src)
            .then((r) => r.text())
            .then((text) => {
                const parsed = Papa.parse(text, { header: true }).data;
                setData(parsed.filter((row) => row.Ticker));
                setLoading(false);
            });
    }, [src]);

    if (loading)
        return (
            <Box sx={{ p: 4, textAlign: "center" }}>
                <CircularProgress />
            </Box>
        );

    if (!data.length)
        return (
            <Typography sx={{ mt: 4, textAlign: "center" }}>
                No holdings data available.
            </Typography>
        );

    const columns = Object.keys(data[0] || {});

    return (
        <TableContainer component={Paper} sx={{ maxWidth: 800, mx: "auto", mt: 2 }}>
            <Table>
                <TableHead>
                    <TableRow>
                        {columns.map((c) => (
                            <TableCell key={c} sx={{ fontWeight: "bold" }}>
                                {c}
                            </TableCell>
                        ))}
                    </TableRow>
                </TableHead>
                <TableBody>
                    {data.map((row, i) => (
                        <TableRow key={i}>
                            {columns.map((c) => (
                                <TableCell key={c}>{row[c]}</TableCell>
                            ))}
                        </TableRow>
                    ))}
                </TableBody>
            </Table>
        </TableContainer>
    );
}
