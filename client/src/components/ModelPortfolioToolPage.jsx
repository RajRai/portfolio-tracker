import React, { useMemo, useState } from "react";
import {
    Alert,
    Box,
    Button,
    Divider,
    LinearProgress,
    MenuItem,
    Paper,
    Select,
    Stack,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableRow,
    TextField,
    Typography,
} from "@mui/material";
import AccountTabs from "./AccountTabs.jsx";
import { SourcePicker, formatPercent, normalizeTicker, postJson } from "./toolsShared.jsx";

const defaultStartDateString = () => {
    const date = new Date();
    date.setFullYear(date.getFullYear() - 1);
    while (date.getDay() === 0 || date.getDay() === 6) {
        date.setDate(date.getDate() - 1);
    }
    return date.toISOString().slice(0, 10);
};

const formatWeightsText = (holdings) =>
    (holdings || [])
        .map((holding) => {
            const weight = holding.source_weight ?? holding.weight ?? 0;
            return `${holding.ticker} ${(Number(weight) * 100).toFixed(2)}`;
        })
        .join("\n");

const parseWeightText = (value) => {
    const lines = String(value || "").split(/\r?\n/);
    const totals = {};
    const order = [];
    const invalidLines = [];
    let totalWeight = 0;

    for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;

        const normalized = trimmed.replace(/[:,=]/g, " ").replace(/\s+/g, " ");
        const match = normalized.match(/^(\$?[A-Za-z0-9][A-Za-z0-9.-]*)\s+([+-]?(?:\d+(?:\.\d*)?|\.\d+))%?$/);
        if (!match) {
            invalidLines.push(trimmed);
            continue;
        }

        const ticker = normalizeTicker(match[1]);
        const weight = Number(match[2]);
        if (!ticker || !Number.isFinite(weight) || weight <= 0) {
            invalidLines.push(trimmed);
            continue;
        }

        if (!(ticker in totals)) {
            totals[ticker] = 0;
            order.push(ticker);
        }
        totals[ticker] += weight;
        totalWeight += weight;
    }

    const rows = order.map((ticker) => ({
        ticker,
        weight: totals[ticker],
        normalizedWeight: totalWeight > 0 ? totals[ticker] / totalWeight : 0,
    }));

    return {
        rows,
        totalWeight,
        invalidLines,
    };
};

function WeightInputSection({
    title,
    description,
    accounts,
    sourceAccountId,
    setSourceAccountId,
    onLoadSource,
    loadingSource,
    sourceSummary,
    value,
    onChange,
    parsed,
    showSourcePicker = true,
}) {
    return (
        <Box>
            <Typography variant="h6" sx={{ fontSize: "1rem", fontWeight: 600, mb: 0.5 }}>
                {title}
            </Typography>
            {description && (
                <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
                    {description}
                </Typography>
            )}

            {showSourcePicker && (
                <Box sx={{ mb: 1.5 }}>
                    <SourcePicker
                        accounts={accounts}
                        accountId={sourceAccountId}
                        setAccountId={setSourceAccountId}
                        onLoad={onLoadSource}
                        loading={loadingSource}
                    />
                </Box>
            )}

            {sourceSummary && (
                <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
                    Loaded weights from {sourceSummary.label}.
                </Typography>
            )}

            <TextField
                fullWidth
                multiline
                minRows={6}
                label={`${title} Weights`}
                value={value}
                onChange={(event) => onChange(event.target.value)}
                placeholder={"AAPL 25\nMSFT 35\nNVDA 40"}
                helperText="One holding per line. Use formats like AAPL 25 or MSFT, 12.5."
            />

            {!!parsed.invalidLines.length && (
                <Alert severity="warning" sx={{ mt: 1.5 }}>
                    Fix {parsed.invalidLines.length} invalid line{parsed.invalidLines.length === 1 ? "" : "s"} before generating the report.
                </Alert>
            )}

            {parsed.rows.length > 0 && (
                <Box sx={{ mt: 1.5 }}>
                    <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                        {parsed.rows.length} holding{parsed.rows.length === 1 ? "" : "s"} loaded.
                        {" "}Weights normalize automatically from a total of {parsed.totalWeight.toFixed(2)}.
                    </Typography>
                    <Table size="small">
                        <TableHead>
                            <TableRow>
                                <TableCell>Ticker</TableCell>
                                <TableCell align="right">Entered Weight</TableCell>
                                <TableCell align="right">Normalized Weight</TableCell>
                            </TableRow>
                        </TableHead>
                        <TableBody>
                            {parsed.rows.map((row) => (
                                <TableRow key={row.ticker}>
                                    <TableCell>{row.ticker}</TableCell>
                                    <TableCell align="right">{row.weight.toFixed(2)}</TableCell>
                                    <TableCell align="right">{formatPercent(row.normalizedWeight)}</TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                </Box>
            )}
        </Box>
    );
}

export default function ModelPortfolioToolPage({ accounts }) {
    const [reportName, setReportName] = useState("Model Portfolio");
    const [startDate, setStartDate] = useState(defaultStartDateString());
    const [portfolioSourceAccountId, setPortfolioSourceAccountId] = useState(accounts[0]?.id || "");
    const [benchmarkSourceAccountId, setBenchmarkSourceAccountId] = useState(accounts[0]?.id || "");
    const [portfolioWeightsText, setPortfolioWeightsText] = useState("");
    const [benchmarkWeightsText, setBenchmarkWeightsText] = useState("");
    const [benchmarkTicker, setBenchmarkTicker] = useState("VT");
    const [benchmarkMode, setBenchmarkMode] = useState("ticker");
    const [portfolioSourceSummary, setPortfolioSourceSummary] = useState(null);
    const [benchmarkSourceSummary, setBenchmarkSourceSummary] = useState(null);
    const [loadingPortfolioSource, setLoadingPortfolioSource] = useState(false);
    const [loadingBenchmarkSource, setLoadingBenchmarkSource] = useState(false);
    const [loadingReport, setLoadingReport] = useState(false);
    const [warnings, setWarnings] = useState([]);
    const [error, setError] = useState("");
    const [viewerAccount, setViewerAccount] = useState(null);

    React.useEffect(() => {
        if (!portfolioSourceAccountId && accounts[0]?.id) {
            setPortfolioSourceAccountId(accounts[0].id);
        }
        if (!benchmarkSourceAccountId && accounts[0]?.id) {
            setBenchmarkSourceAccountId(accounts[0].id);
        }
    }, [accounts, benchmarkSourceAccountId, portfolioSourceAccountId]);

    const portfolioParsed = useMemo(() => parseWeightText(portfolioWeightsText), [portfolioWeightsText]);
    const benchmarkParsed = useMemo(() => parseWeightText(benchmarkWeightsText), [benchmarkWeightsText]);

    const loadSourceWeights = async (accountId, setter, summarySetter, loadingSetter) => {
        loadingSetter(true);
        setError("");
        try {
            const payload = await postJson("/api/tools/stock-source", {
                sourceType: "portfolio",
                accountId,
            });
            setter(formatWeightsText(payload.holdings || []));
            summarySetter(payload.source || null);
        } catch (err) {
            setError(err.message);
        } finally {
            loadingSetter(false);
        }
    };

    const loadPortfolioSource = async () => {
        await loadSourceWeights(
            portfolioSourceAccountId,
            setPortfolioWeightsText,
            setPortfolioSourceSummary,
            setLoadingPortfolioSource
        );
    };

    const loadBenchmarkSource = async () => {
        await loadSourceWeights(
            benchmarkSourceAccountId,
            setBenchmarkWeightsText,
            setBenchmarkSourceSummary,
            setLoadingBenchmarkSource
        );
    };

    const benchmarkNeedsWeights = benchmarkMode === "existingPortfolio" || benchmarkMode === "customPortfolio";
    const canGenerate =
        !!reportName.trim() &&
        !!startDate &&
        portfolioParsed.rows.length > 0 &&
        portfolioParsed.invalidLines.length === 0 &&
        (
            benchmarkMode === "ticker"
                ? !!normalizeTicker(benchmarkTicker)
                : benchmarkParsed.rows.length > 0 && benchmarkParsed.invalidLines.length === 0
        );

    const generateReport = async () => {
        setLoadingReport(true);
        setError("");
        setWarnings([]);
        setViewerAccount(null);

        try {
            const payload = await postJson("/api/tools/model-portfolio-report", {
                reportName,
                startDate,
                holdings: portfolioParsed.rows.map((row) => ({
                    ticker: row.ticker,
                    weight: row.weight,
                })),
                benchmark:
                    benchmarkMode === "ticker"
                        ? {
                            mode: "ticker",
                            ticker: normalizeTicker(benchmarkTicker),
                        }
                        : {
                            mode: "portfolio",
                            label:
                                benchmarkMode === "existingPortfolio"
                                    ? benchmarkSourceSummary?.label || "Benchmark Portfolio"
                                    : "Custom Benchmark Portfolio",
                            holdings: benchmarkParsed.rows.map((row) => ({
                                ticker: row.ticker,
                                weight: row.weight,
                            })),
                        },
            });
            setWarnings(payload.warnings || []);
            setViewerAccount(payload.account || null);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoadingReport(false);
        }
    };

    return (
        <Box sx={{ width: "100%", maxWidth: 1400, mx: "auto", px: { xs: 1.5, sm: 3 }, py: 3 }}>
            <Typography variant="h4" sx={{ fontWeight: 700, mb: 0.5 }}>
                Model Portfolio Report
            </Typography>
            <Typography color="text.secondary" sx={{ mb: 2 }}>
                Generate a point-in-time report from model weights and compare it against a ticker or another weighted portfolio.
            </Typography>

            <Paper sx={{ p: { xs: 1.5, sm: 2 }, borderRadius: 2, mb: 2 }}>
                <Stack spacing={2}>
                    <Stack direction={{ xs: "column", md: "row" }} spacing={1.5}>
                        <TextField
                            fullWidth
                            size="small"
                            label="Report Name"
                            value={reportName}
                            onChange={(event) => setReportName(event.target.value)}
                        />
                        <TextField
                            size="small"
                            type="date"
                            label="Start Date"
                            value={startDate}
                            onChange={(event) => setStartDate(event.target.value)}
                            InputLabelProps={{ shrink: true }}
                            sx={{ minWidth: { md: 220 } }}
                            helperText="Uses the next available trading day on or after this date."
                        />
                    </Stack>

                    <WeightInputSection
                        title="Model Portfolio"
                        description="Enter the weights you want to backtest, or seed them from an existing portfolio."
                        accounts={accounts}
                        sourceAccountId={portfolioSourceAccountId}
                        setSourceAccountId={setPortfolioSourceAccountId}
                        onLoadSource={loadPortfolioSource}
                        loadingSource={loadingPortfolioSource}
                        sourceSummary={portfolioSourceSummary}
                        value={portfolioWeightsText}
                        onChange={setPortfolioWeightsText}
                        parsed={portfolioParsed}
                    />

                    <Divider />

                    <Box>
                        <Typography variant="h6" sx={{ fontSize: "1rem", fontWeight: 600, mb: 1 }}>
                            Benchmark
                        </Typography>
                        <Stack spacing={1.5}>
                            <Select
                                size="small"
                                value={benchmarkMode}
                                onChange={(event) => setBenchmarkMode(event.target.value)}
                                sx={{ maxWidth: 320 }}
                            >
                                <MenuItem value="ticker">Ticker</MenuItem>
                                <MenuItem value="existingPortfolio">Existing Portfolio</MenuItem>
                                <MenuItem value="customPortfolio">Custom Portfolio</MenuItem>
                            </Select>

                            {benchmarkMode === "ticker" ? (
                                <TextField
                                    size="small"
                                    label="Benchmark Ticker"
                                    value={benchmarkTicker}
                                    onChange={(event) => setBenchmarkTicker(event.target.value.toUpperCase())}
                                    placeholder="VT"
                                    sx={{ maxWidth: 240 }}
                                />
                            ) : (
                                <WeightInputSection
                                    title={benchmarkMode === "existingPortfolio" ? "Benchmark Portfolio" : "Custom Benchmark"}
                                    description={
                                        benchmarkMode === "existingPortfolio"
                                            ? "Load an existing portfolio as the benchmark source, then edit if needed."
                                            : "Enter custom benchmark weights."
                                    }
                                    accounts={accounts}
                                    sourceAccountId={benchmarkSourceAccountId}
                                    setSourceAccountId={setBenchmarkSourceAccountId}
                                    onLoadSource={loadBenchmarkSource}
                                    loadingSource={loadingBenchmarkSource}
                                    sourceSummary={benchmarkSourceSummary}
                                    value={benchmarkWeightsText}
                                    onChange={setBenchmarkWeightsText}
                                    parsed={benchmarkParsed}
                                    showSourcePicker={benchmarkNeedsWeights && benchmarkMode === "existingPortfolio"}
                                />
                            )}
                        </Stack>
                    </Box>

                    <Stack direction="row" spacing={1} alignItems="center">
                        <Button
                            variant="contained"
                            onClick={generateReport}
                            disabled={!canGenerate || loadingReport}
                        >
                            Generate Report
                        </Button>
                    </Stack>
                </Stack>

                {loadingReport && <LinearProgress sx={{ mt: 2 }} />}
            </Paper>

            {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
            {warnings.map((warning) => (
                <Alert key={warning} severity="warning" sx={{ mb: 1 }}>
                    {warning}
                </Alert>
            ))}

            <Paper sx={{ borderRadius: 2, overflow: "hidden", minHeight: viewerAccount ? "80vh" : "auto" }}>
                {viewerAccount ? (
                    <Box sx={{ height: "80vh", display: "flex" }}>
                        <AccountTabs account={viewerAccount} liveStore={null} />
                    </Box>
                ) : (
                    <Box sx={{ p: { xs: 1.5, sm: 2 } }}>
                        <Typography variant="body2" color="text.secondary">
                            Generated reports open here in a dedicated viewer.
                        </Typography>
                    </Box>
                )}
            </Paper>
        </Box>
    );
}
