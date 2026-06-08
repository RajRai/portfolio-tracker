import React, { useState } from "react";
import {
    Alert,
    Box,
    Button,
    Chip,
    LinearProgress,
    Paper,
    Stack,
    TextField,
    Typography,
} from "@mui/material";
import { postJson } from "./toolsShared.jsx";
import { serializeQuery, trackToolEvent } from "../umami.js";

const EXAMPLE_TEXT = `ticker,targetBuyPrice,targetSellPrice
AMD,53.44,73.48
SRAD,18.24,25.08
DT,39.58,54.42`;

export default function AlgoOutputProcessorPage() {
    const [rawText, setRawText] = useState("");
    const [data, setData] = useState(null);
    const [warnings, setWarnings] = useState([]);
    const [error, setError] = useState("");
    const [loading, setLoading] = useState(false);

    const runProcessor = async () => {
        const query = { rawText };
        setLoading(true);
        setError("");
        setWarnings([]);

        trackToolEvent("algo_output_processor", "run_started", {
            query: serializeQuery({ rawTextLength: rawText.length }),
        });

        try {
            const payload = await postJson("/api/tools/algo-output-processor", query);
            setData(payload);
            setWarnings(payload.warnings || []);
            trackToolEvent("algo_output_processor", "run_completed", {
                query: serializeQuery({ rawTextLength: rawText.length }),
                row_count: payload.summary?.total || 0,
                buy_count: payload.summary?.buy || 0,
                sell_count: payload.summary?.sell || 0,
                hold_count: payload.summary?.hold || 0,
                unpriced_count: payload.summary?.unpriced || 0,
            });
        } catch (err) {
            setError(err.message);
            setData(null);
            trackToolEvent("algo_output_processor", "run_failed", {
                query: serializeQuery({ rawTextLength: rawText.length }),
                error: err.message,
            });
        } finally {
            setLoading(false);
        }
    };

    return (
        <Box sx={{ width: "100%", maxWidth: 1400, mx: "auto", px: { xs: 1.5, sm: 3 }, py: 3 }}>
            <Typography variant="h4" sx={{ fontWeight: 700, mb: 0.5 }}>
                Algo Output Processor
            </Typography>
            <Typography color="text.secondary" sx={{ mb: 2 }}>
                Paste wrapped algo output or plain CSV.
            </Typography>

            <Paper sx={{ p: { xs: 1.5, sm: 2 }, borderRadius: 2, mb: 2 }}>
                <Stack spacing={2}>
                    <TextField
                        fullWidth
                        multiline
                        minRows={10}
                        label="Algo output"
                        value={rawText}
                        onChange={(event) => setRawText(event.target.value)}
                        placeholder={EXAMPLE_TEXT}
                        helperText="Required columns: ticker, targetBuyPrice, targetSellPrice."
                    />

                    <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }}>
                        <Button variant="contained" onClick={runProcessor} disabled={!rawText.trim() || loading}>
                            Process Output
                        </Button>
                        <Button
                            variant="text"
                            onClick={() => setRawText(EXAMPLE_TEXT)}
                            disabled={loading}
                        >
                            Load Example
                        </Button>
                    </Stack>
                </Stack>

                {loading && <LinearProgress sx={{ mt: 2 }} />}
            </Paper>

            {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
            {warnings.map((warning) => (
                <Alert key={warning} severity="warning" sx={{ mb: 1 }}>
                    {warning}
                </Alert>
            ))}

            <Paper sx={{ p: { xs: 1.5, sm: 2 }, borderRadius: 2, overflowX: "auto" }}>
                {!data && !loading && (
                    <Typography variant="body2" color="text.secondary">
                        No results yet.
                    </Typography>
                )}

                {data && (
                    <Stack spacing={2}>
                        <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                            <Chip label={`Rows ${data.summary?.total || 0}`} variant="outlined" />
                            <Chip label={`Buy ${data.summary?.buy || 0}`} color="success" variant="outlined" />
                            <Chip label={`Sell ${data.summary?.sell || 0}`} color="error" variant="outlined" />
                            <Chip label={`Hold ${data.summary?.hold || 0}`} color="warning" variant="outlined" />
                            {!!data.summary?.unpriced && (
                                <Chip label={`Unpriced ${data.summary.unpriced}`} variant="outlined" />
                            )}
                        </Stack>

                        <ClassificationGroup
                            title="Buy"
                            color="success"
                            tickers={data.groups?.buy || []}
                        />
                        <ClassificationGroup
                            title="Sell"
                            color="error"
                            tickers={data.groups?.sell || []}
                        />
                        <ClassificationGroup
                            title="Hold"
                            color="warning"
                            tickers={data.groups?.hold || []}
                        />
                    </Stack>
                )}
            </Paper>
        </Box>
    );
}

function ClassificationGroup({ title, color, tickers }) {
    return (
        <Box>
            <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>
                {title}
            </Typography>
            {tickers.length ? (
                <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                    {tickers.map((ticker) => (
                        <Chip key={`${title}-${ticker}`} label={ticker} color={color} variant="outlined" />
                    ))}
                </Stack>
            ) : (
                <Typography variant="body2" color="text.secondary">
                    No tickers.
                </Typography>
            )}
        </Box>
    );
}
