import React, { useMemo, useState } from "react";
import {
    Alert,
    Box,
    Button,
    Checkbox,
    Divider,
    FormControlLabel,
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

const rollWeekendBack = (date) => {
    const next = new Date(date);
    while (next.getDay() === 0 || next.getDay() === 6) {
        next.setDate(next.getDate() - 1);
    }
    return next;
};

const defaultStartDateString = () => {
    const date = new Date();
    date.setFullYear(date.getFullYear() - 1);
    return rollWeekendBack(date).toISOString().slice(0, 10);
};

const defaultEndDateString = () => rollWeekendBack(new Date()).toISOString().slice(0, 10);

const scopeLabel = (scope) =>
    scope === "both" ? "Both" : scope === "benchmark" ? "Benchmark" : "Portfolio";

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
        const match = normalized.match(/^(\$?[A-Za-z0-9][A-Za-z0-9.-]*)(?:\s+([+-]?(?:\d+(?:\.\d*)?|\.\d+))%?)?$/);
        if (!match) {
            invalidLines.push(trimmed);
            continue;
        }

        const ticker = normalizeTicker(match[1]);
        const weight = match[2] == null ? 1 : Number(match[2]);
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
    useMarketCapWeights,
    onUseMarketCapWeightsChange,
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
                placeholder={"AAPL\nMSFT 35\nNVDA 40"}
                helperText="One holding per line. Use formats like AAPL, AAPL 25, or MSFT 12.5. Bare tickers default to weight 1."
            />

            <FormControlLabel
                sx={{ mt: 1 }}
                control={
                    <Checkbox
                        size="small"
                        checked={useMarketCapWeights}
                        onChange={(event) => onUseMarketCapWeightsChange(event.target.checked)}
                    />
                }
                label="Market cap weight as of the start date when possible"
            />

            {!!parsed.invalidLines.length && (
                <Alert severity="warning" sx={{ mt: 1.5 }}>
                    Fix {parsed.invalidLines.length} invalid line{parsed.invalidLines.length === 1 ? "" : "s"} before generating the report.
                </Alert>
            )}

            {useMarketCapWeights && (
                <Alert severity="info" sx={{ mt: 1.5 }}>
                    Entered weights are used only as a fallback here. When possible, the tool will estimate start-date market caps from current market cap and the historical price ratio.
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
    const [endDate, setEndDate] = useState(defaultEndDateString());
    const [portfolioSourceAccountId, setPortfolioSourceAccountId] = useState(accounts[0]?.id || "");
    const [benchmarkSourceAccountId, setBenchmarkSourceAccountId] = useState(accounts[0]?.id || "");
    const [portfolioWeightsText, setPortfolioWeightsText] = useState("");
    const [benchmarkWeightsText, setBenchmarkWeightsText] = useState("");
    const [benchmarkTicker, setBenchmarkTicker] = useState("VT");
    const [benchmarkMode, setBenchmarkMode] = useState("ticker");
    const [portfolioUseMarketCapWeights, setPortfolioUseMarketCapWeights] = useState(false);
    const [benchmarkUseMarketCapWeights, setBenchmarkUseMarketCapWeights] = useState(false);
    const [portfolioSourceSummary, setPortfolioSourceSummary] = useState(null);
    const [benchmarkSourceSummary, setBenchmarkSourceSummary] = useState(null);
    const [loadingPortfolioSource, setLoadingPortfolioSource] = useState(false);
    const [loadingBenchmarkSource, setLoadingBenchmarkSource] = useState(false);
    const [loadingReport, setLoadingReport] = useState(false);
    const [warnings, setWarnings] = useState([]);
    const [error, setError] = useState("");
    const [viewerAccount, setViewerAccount] = useState(null);
    const [rangeInfo, setRangeInfo] = useState(null);

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
    const datesValid = !startDate || !endDate || startDate <= endDate;
    const canGenerate =
        !!reportName.trim() &&
        !!startDate &&
        !!endDate &&
        datesValid &&
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
        setRangeInfo(null);

        try {
            const payload = await postJson("/api/tools/model-portfolio-report", {
                reportName,
                startDate,
                endDate,
                weightingMode: portfolioUseMarketCapWeights ? "market_cap_start" : "manual",
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
                            weightingMode: benchmarkUseMarketCapWeights ? "market_cap_start" : "manual",
                            holdings: benchmarkParsed.rows.map((row) => ({
                                ticker: row.ticker,
                                weight: row.weight,
                            })),
                        },
            });
            setWarnings(payload.warnings || []);
            setViewerAccount(payload.account || null);
            setRangeInfo(payload.rangeInfo || null);
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
                        <TextField
                            size="small"
                            type="date"
                            label="End Date"
                            value={endDate}
                            onChange={(event) => setEndDate(event.target.value)}
                            InputLabelProps={{ shrink: true }}
                            sx={{ minWidth: { md: 220 } }}
                            helperText="Uses the last available trading day on or before this date."
                        />
                    </Stack>

                    {!datesValid && (
                        <Alert severity="warning">
                            End date must be on or after the start date.
                        </Alert>
                    )}

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
                        useMarketCapWeights={portfolioUseMarketCapWeights}
                        onUseMarketCapWeightsChange={setPortfolioUseMarketCapWeights}
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
                                    useMarketCapWeights={benchmarkUseMarketCapWeights}
                                    onUseMarketCapWeightsChange={setBenchmarkUseMarketCapWeights}
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

            {rangeInfo && (
                <Paper sx={{ p: { xs: 1.5, sm: 2 }, borderRadius: 2, mb: 2 }}>
                    <Typography variant="h6" sx={{ fontSize: "1rem", fontWeight: 600, mb: 0.75 }}>
                        Data Availability
                    </Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
                        Requested window: {rangeInfo.requestedStartDate} through {rangeInfo.requestedEndDate}
                    </Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
                        Common report window: {rangeInfo.effectiveStartDate} through {rangeInfo.effectiveEndDate}
                    </Typography>

                    {!!rangeInfo.startLimitedBy?.length && (
                        <Typography variant="body2" sx={{ mb: 0.5 }}>
                            Start limited by: {rangeInfo.startLimitedBy.join(", ")}
                        </Typography>
                    )}
                    {!!rangeInfo.endLimitedBy?.length && (
                        <Typography variant="body2" sx={{ mb: 1.5 }}>
                            End limited by: {rangeInfo.endLimitedBy.join(", ")}
                        </Typography>
                    )}

                    <Table size="small">
                        <TableHead>
                            <TableRow>
                                <TableCell>Ticker</TableCell>
                                <TableCell>Scope</TableCell>
                                <TableCell align="right">First Date</TableCell>
                                <TableCell align="right">Last Date</TableCell>
                                <TableCell align="center">Limits Start</TableCell>
                                <TableCell align="center">Limits End</TableCell>
                            </TableRow>
                        </TableHead>
                        <TableBody>
                            {(rangeInfo.symbolRanges || []).map((row) => (
                                <TableRow key={row.ticker}>
                                    <TableCell>{row.ticker}</TableCell>
                                    <TableCell>{scopeLabel(row.scope)}</TableCell>
                                    <TableCell align="right">{row.firstDate || "\u2014"}</TableCell>
                                    <TableCell align="right">{row.lastDate || "\u2014"}</TableCell>
                                    <TableCell align="center">{row.limitsStart ? "Yes" : ""}</TableCell>
                                    <TableCell align="center">{row.limitsEnd ? "Yes" : ""}</TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                </Paper>
            )}

            <Paper sx={{ borderRadius: 2, overflow: "hidden" }}>
                {viewerAccount ? (
                    <Box>
                        <AccountTabs account={viewerAccount} liveStore={null} embedded />
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
