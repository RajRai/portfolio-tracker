import React, { useState } from "react";
import {
    Alert,
    Box,
    Button,
    Checkbox,
    Chip,
    FormControlLabel,
    LinearProgress,
    Paper,
    Stack,
    TextField,
    Typography,
} from "@mui/material";
import { alpha } from "@mui/material/styles";
import { postJson } from "./toolsShared.jsx";
import { trackToolEvent } from "../umami.js";

const EXAMPLE_TEXT = `ticker,targetBuyPrice,targetSellPrice
AMD,53.44,73.48
SRAD,18.24,25.08
DT,39.58,54.42`;

const PORTFOLIO_EXAMPLE_TEXT = `Symbol\tCurrent weight\tTarget weight\tAction
NVDA\t7.3 %\t7.2 %\tDelete
ACAD\t7.3 %\t7.2 %\tDelete
POWL\t7.2 %\t7.1 %\tDelete
CART\t7.2 %\t7.2 %\tDelete
AGX\t7.0 %\t7.1 %\tDelete
DOCU\t7.0 %\t7.1 %\tDelete
FSLR\t6.9 %\t7.1 %\tDelete`;

const PORTFOLIO_TICKER_LIST_EXAMPLE = `NVDA
ACAD
POWL
CART
AGX
DOCU
FSLR`;

export default function AlgoOutputProcessorPage() {
    const [rawText, setRawText] = useState("");
    const [portfolioRawText, setPortfolioRawText] = useState("");
    const [includePortfolioActions, setIncludePortfolioActions] = useState(false);
    const [data, setData] = useState(null);
    const [warnings, setWarnings] = useState([]);
    const [error, setError] = useState("");
    const [loading, setLoading] = useState(false);
    const showSplitResults = Boolean(data?.priceSignals && data?.portfolioActions);

    const runProcessor = async () => {
        const query = {
            rawText,
            portfolioRawText,
            includePortfolioActions,
        };
        setLoading(true);
        setError("");
        setWarnings([]);

        trackToolEvent("algo_output_processor", "run_started", {
            raw_text_length: rawText.length,
            portfolio_raw_text_length: portfolioRawText.length,
            include_portfolio_actions: includePortfolioActions,
        });

        try {
            const payload = await postJson("/api/tools/algo-output-processor", query);
            setData(payload);
            setWarnings(payload.warnings || []);
            trackToolEvent("algo_output_processor", "run_completed", {
                raw_text_length: rawText.length,
                portfolio_raw_text_length: portfolioRawText.length,
                include_portfolio_actions: includePortfolioActions,
                price_row_count: payload.priceSignals?.summary?.total || 0,
                portfolio_action_row_count: payload.portfolioActions?.summary?.total || 0,
            });
        } catch (err) {
            setError(err.message);
            setData(null);
            trackToolEvent("algo_output_processor", "run_failed", {
                raw_text_length: rawText.length,
                portfolio_raw_text_length: portfolioRawText.length,
                include_portfolio_actions: includePortfolioActions,
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
                Paste price targets, current holdings, or both.
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

                    <FormControlLabel
                        control={(
                            <Checkbox
                                checked={includePortfolioActions}
                                onChange={(event) => setIncludePortfolioActions(event.target.checked)}
                            />
                        )}
                        label="Also paste current portfolio holdings"
                    />

                    {includePortfolioActions && (
                        <TextField
                            fullWidth
                            multiline
                            minRows={10}
                            label="Current portfolio holdings"
                            value={portfolioRawText}
                            onChange={(event) => setPortfolioRawText(event.target.value)}
                            placeholder={PORTFOLIO_EXAMPLE_TEXT}
                            helperText="We only check whether each algo ticker appears anywhere in this pasted dump."
                        />
                    )}

                    <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }}>
                        <Button
                            variant="contained"
                            onClick={runProcessor}
                            disabled={!rawText.trim() || (includePortfolioActions && !portfolioRawText.trim()) || loading}
                        >
                            Process Output
                        </Button>
                        <Button
                            variant="text"
                            onClick={() => setRawText(EXAMPLE_TEXT)}
                            disabled={loading}
                        >
                            Load Price Example
                        </Button>
                        {includePortfolioActions && (
                            <Button
                                variant="text"
                                onClick={() => setPortfolioRawText(PORTFOLIO_EXAMPLE_TEXT)}
                                disabled={loading}
                            >
                                Load Portfolio Example 1
                            </Button>
                        )}
                        {includePortfolioActions && (
                            <Button
                                variant="text"
                                onClick={() => setPortfolioRawText(PORTFOLIO_TICKER_LIST_EXAMPLE)}
                                disabled={loading}
                            >
                                Load Portfolio Example 2
                            </Button>
                        )}
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
                    <Box
                        sx={{
                            display: "grid",
                            gridTemplateColumns: {
                                xs: "1fr",
                                xl: showSplitResults ? "repeat(2, minmax(0, 1fr))" : "1fr",
                            },
                            gap: 2,
                            alignItems: "start",
                        }}
                    >
                        {data.priceSignals && (
                            <SignalSection
                                title="Price Targets"
                                subtitle="Live price vs buy and sell targets."
                                signals={data.priceSignals}
                                showUnpriced
                                tone="info"
                            />
                        )}
                        {data.portfolioActions && (
                            <SignalSection
                                title="Portfolio Actions"
                                subtitle="Only buys names you do not hold and sells names you do."
                                signals={data.portfolioActions}
                                showUnpriced
                                tone="warning"
                            />
                        )}
                    </Box>
                )}
            </Paper>
        </Box>
    );
}

function SignalSection({ title, subtitle, signals, showUnpriced = false, tone = "primary" }) {
    return (
        <Paper
            variant="outlined"
            sx={(theme) => ({
                p: { xs: 1.5, sm: 2 },
                borderRadius: 2.5,
                borderColor: alpha(theme.palette[tone].main, 0.3),
                background: `linear-gradient(180deg, ${alpha(theme.palette[tone].main, 0.08)} 0%, ${theme.palette.background.paper} 42%)`,
            })}
        >
            <Box
                sx={(theme) => ({
                    pl: 1.25,
                    mb: 1.5,
                    borderLeft: `4px solid ${theme.palette[tone].main}`,
                })}
            >
                <Typography
                    variant="overline"
                    sx={(theme) => ({
                        display: "block",
                        fontWeight: 700,
                        letterSpacing: 1,
                        color: theme.palette[tone].main,
                        lineHeight: 1.4,
                    })}
                >
                    {title}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                    {subtitle}
                </Typography>
            </Box>

            <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ mb: 1.75 }}>
                <Chip label={`Rows ${signals.summary?.total || 0}`} variant="outlined" />
                <Chip label={`Buy ${signals.summary?.buy || 0}`} color="success" variant="outlined" />
                <Chip label={`Sell ${signals.summary?.sell || 0}`} color="error" variant="outlined" />
                <Chip label={`Hold ${signals.summary?.hold || 0}`} color="warning" variant="outlined" />
                {showUnpriced && !!signals.summary?.unpriced && (
                    <Chip label={`Unpriced ${signals.summary.unpriced}`} variant="outlined" />
                )}
            </Stack>

            <Stack spacing={1.25}>
                <ClassificationGroup
                    title="Buy"
                    color="success"
                    tickers={signals.groups?.buy || []}
                />
                <ClassificationGroup
                    title="Sell"
                    color="error"
                    tickers={signals.groups?.sell || []}
                />
                <ClassificationGroup
                    title="Hold"
                    color="warning"
                    tickers={signals.groups?.hold || []}
                />
            </Stack>
        </Paper>
    );
}

function ClassificationGroup({ title, color, tickers }) {
    return (
        <Box
            sx={(theme) => ({
                p: 1.25,
                borderRadius: 2,
                border: "1px solid",
                borderColor: alpha(theme.palette[color].main, 0.22),
                backgroundColor: alpha(theme.palette[color].main, 0.05),
            })}
        >
            <Stack
                direction="row"
                spacing={1}
                alignItems="center"
                justifyContent="space-between"
                sx={{ mb: 1 }}
            >
                <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
                    {title}
                </Typography>
                <Chip size="small" label={tickers.length} color={color} variant="outlined" />
            </Stack>
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
