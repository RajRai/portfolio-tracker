import React, { useMemo, useState } from "react";
import {
    Alert,
    Box,
    Button,
    Checkbox,
    Chip,
    Divider,
    FormControl,
    InputLabel,
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

const todayString = () => new Date().toISOString().slice(0, 10);

const futureDateString = (days) => {
    const date = new Date();
    date.setDate(date.getDate() + days);
    return date.toISOString().slice(0, 10);
};

const splitTickers = (value) =>
    String(value || "")
        .toUpperCase()
        .split(/[\s,;]+/)
        .map((ticker) => ticker.trim().replace(/^\$/, ""))
        .filter((ticker) => /^[A-Z0-9][A-Z0-9.-]*$/.test(ticker));

const formatPercent = (value) =>
    value == null ? "" : `${(Number(value) * 100).toFixed(2)}%`;

const formatCurrency = (value) => {
    if (value == null || Number.isNaN(Number(value))) return "";
    return new Intl.NumberFormat(undefined, {
        style: "currency",
        currency: "USD",
        notation: "compact",
        maximumFractionDigits: 2,
    }).format(Number(value));
};

const formatNumber = (value) => {
    if (value == null || Number.isNaN(Number(value))) return "";
    return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(Number(value));
};

async function postJson(url, body) {
    const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
        throw new Error(payload.error || "Request failed");
    }
    return payload;
}

function StockListEditor({ tickers, onChange, sourceHoldings }) {
    const [entry, setEntry] = useState("");
    const sourceWeightByTicker = useMemo(
        () => Object.fromEntries((sourceHoldings || []).map((holding) => [holding.ticker, holding.source_weight])),
        [sourceHoldings]
    );

    const addTickers = () => {
        const next = [...tickers];
        const seen = new Set(next);
        for (const ticker of splitTickers(entry)) {
            if (!seen.has(ticker)) {
                seen.add(ticker);
                next.push(ticker);
            }
        }
        onChange(next);
        setEntry("");
    };

    const removeTicker = (ticker) => {
        onChange(tickers.filter((item) => item !== ticker));
    };

    return (
        <Box>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mb: 1.5 }}>
                <TextField
                    fullWidth
                    size="small"
                    label="Add tickers"
                    value={entry}
                    onChange={(event) => setEntry(event.target.value)}
                    onKeyDown={(event) => {
                        if (event.key === "Enter") {
                            event.preventDefault();
                            addTickers();
                        }
                    }}
                    placeholder="AAPL MSFT NVDA"
                />
                <Button variant="contained" onClick={addTickers} disabled={!entry.trim()}>
                    Add
                </Button>
            </Stack>

            <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap">
                {tickers.map((ticker) => {
                    const sourceWeight = sourceWeightByTicker[ticker];
                    const label = sourceWeight == null ? ticker : `${ticker} (${formatPercent(sourceWeight)})`;
                    return (
                        <Chip
                            key={ticker}
                            label={label}
                            onDelete={() => removeTicker(ticker)}
                            size="small"
                            variant="outlined"
                        />
                    );
                })}
            </Stack>

            {!tickers.length && (
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                    Load a portfolio or add tickers manually.
                </Typography>
            )}
        </Box>
    );
}

function SourcePicker({
    accounts,
    accountId,
    setAccountId,
    onLoad,
    loading,
}) {
    return (
        <Stack direction={{ xs: "column", md: "row" }} spacing={1.25} alignItems={{ md: "center" }}>
            <FormControl size="small" sx={{ minWidth: 260 }} disabled={!accounts.length}>
                <InputLabel>Portfolio</InputLabel>
                <Select
                    value={accountId}
                    label="Portfolio"
                    onChange={(event) => setAccountId(event.target.value)}
                >
                    {accounts.map((account) => (
                        <MenuItem key={account.id} value={account.id}>
                            {account.name}
                        </MenuItem>
                    ))}
                </Select>
            </FormControl>

            <Button
                variant="outlined"
                onClick={onLoad}
                disabled={loading || !accountId}
            >
                Load Portfolio
            </Button>
        </Stack>
    );
}

function MarketCapResults({ data, sourceHoldings }) {
    const [included, setIncluded] = useState({});
    const sourceWeightByTicker = useMemo(
        () => Object.fromEntries((sourceHoldings || []).map((holding) => [holding.ticker, holding.source_weight])),
        [sourceHoldings]
    );
    const rows = data?.rows || [];

    React.useEffect(() => {
        if (!rows.length) {
            setIncluded({});
            return;
        }

        setIncluded((prev) => {
            const next = {};
            for (const row of rows) {
                next[row.ticker] = prev[row.ticker] ?? true;
            }
            return next;
        });
    }, [rows]);

    const displayRows = useMemo(() => {
        const includedTotal = rows.reduce(
            (sum, row) => sum + (included[row.ticker] && row.market_cap ? Number(row.market_cap) : 0),
            0
        );

        return rows.map((row) => ({
            ...row,
            adjusted_weight:
                included[row.ticker] && row.market_cap && includedTotal > 0
                    ? Number(row.market_cap) / includedTotal
                    : 0,
        }));
    }, [rows, included]);

    if (!data) return null;

    return (
        <Box>
            <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>
                Total market cap: {formatCurrency(data.total_market_cap)}
            </Typography>
            <Table size="small">
                <TableHead>
                <TableRow>
                    <TableCell padding="checkbox">Use</TableCell>
                    <TableCell>Ticker</TableCell>
                    <TableCell>Name</TableCell>
                    <TableCell align="right">Market Cap</TableCell>
                    <TableCell align="right">Market Weight</TableCell>
                    <TableCell align="right">Source Weight</TableCell>
                    <TableCell>Method</TableCell>
                    <TableCell>Note</TableCell>
                </TableRow>
                </TableHead>
                <TableBody>
                {displayRows.map((row) => (
                    <TableRow key={row.ticker}>
                        <TableCell padding="checkbox">
                            <Checkbox
                                size="small"
                                checked={included[row.ticker] ?? true}
                                onChange={(event) => {
                                    setIncluded((prev) => ({
                                        ...prev,
                                        [row.ticker]: event.target.checked,
                                    }));
                                }}
                                disabled={!row.market_cap}
                            />
                        </TableCell>
                        <TableCell>{row.ticker}</TableCell>
                        <TableCell>{row.name}</TableCell>
                        <TableCell align="right">{formatCurrency(row.market_cap)}</TableCell>
                        <TableCell align="right">{formatPercent(row.adjusted_weight)}</TableCell>
                        <TableCell align="right">{formatPercent(sourceWeightByTicker[row.ticker])}</TableCell>
                        <TableCell>{row.valuation_method || ""}</TableCell>
                        <TableCell>{row.note || ""}</TableCell>
                    </TableRow>
                ))}
                </TableBody>
            </Table>
        </Box>
    );
}

function EarningsResults({ data }) {
    if (!data) return null;

    if (!data.events?.length) {
        return (
            <Typography variant="body2" color="text.secondary">
                No earnings events found for this list and date range.
            </Typography>
        );
    }

    return (
        <Table size="small">
            <TableHead>
            <TableRow>
                <TableCell>Date</TableCell>
                <TableCell>Ticker</TableCell>
                <TableCell>Company</TableCell>
                <TableCell>Time</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>Fiscal</TableCell>
                <TableCell align="right">EPS Est.</TableCell>
                <TableCell align="right">EPS Actual</TableCell>
                <TableCell align="right">Revenue Est.</TableCell>
                <TableCell align="right">Revenue Actual</TableCell>
            </TableRow>
            </TableHead>
            <TableBody>
            {data.events.map((event, index) => (
                <TableRow key={`${event.ticker}-${event.date}-${event.time || ""}-${index}`}>
                    <TableCell>{event.date}</TableCell>
                    <TableCell>{event.ticker}</TableCell>
                    <TableCell>{event.company_name || ""}</TableCell>
                    <TableCell>{event.time || ""}</TableCell>
                    <TableCell>{event.date_status || ""}</TableCell>
                    <TableCell>
                        {[event.fiscal_period, event.fiscal_year].filter(Boolean).join(" ")}
                    </TableCell>
                    <TableCell align="right">{formatNumber(event.estimated_eps)}</TableCell>
                    <TableCell align="right">{formatNumber(event.actual_eps)}</TableCell>
                    <TableCell align="right">{formatCurrency(event.estimated_revenue)}</TableCell>
                    <TableCell align="right">{formatCurrency(event.actual_revenue)}</TableCell>
                </TableRow>
            ))}
            </TableBody>
        </Table>
    );
}

export default function StockToolsPage({ tool, accounts }) {
    const isEarnings = tool === "earnings";
    const [accountId, setAccountId] = useState(accounts[0]?.id || "");
    const [tickers, setTickers] = useState([]);
    const [sourceHoldings, setSourceHoldings] = useState([]);
    const [sourceSummary, setSourceSummary] = useState(null);
    const [warnings, setWarnings] = useState([]);
    const [error, setError] = useState("");
    const [loadingSource, setLoadingSource] = useState(false);
    const [loadingResults, setLoadingResults] = useState(false);
    const [marketCapData, setMarketCapData] = useState(null);
    const [earningsData, setEarningsData] = useState(null);
    const [startDate, setStartDate] = useState(todayString());
    const [endDate, setEndDate] = useState(futureDateString(90));

    React.useEffect(() => {
        if (!accountId && accounts[0]?.id) {
            setAccountId(accounts[0].id);
        }
    }, [accountId, accounts]);

    const loadSource = async () => {
        setError("");
        setWarnings([]);
        setLoadingSource(true);
        setMarketCapData(null);
        setEarningsData(null);

        try {
            const payload = await postJson("/api/tools/stock-source", {
                sourceType: "portfolio",
                accountId,
            });
            setTickers(payload.tickers || []);
            setSourceHoldings(payload.holdings || []);
            setSourceSummary(payload.source || null);
            setWarnings(payload.warnings || []);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoadingSource(false);
        }
    };

    const runTool = async () => {
        setError("");
        setWarnings([]);
        setLoadingResults(true);

        try {
            if (isEarnings) {
                const payload = await postJson("/api/tools/earnings-calendar", {
                    tickers,
                    start: startDate,
                    end: endDate,
                });
                setEarningsData(payload);
                setWarnings(payload.warnings || []);
            } else {
                const payload = await postJson("/api/tools/market-cap-weights", { tickers });
                setMarketCapData(payload);
                setWarnings(payload.missing?.length ? [`Missing market caps: ${payload.missing.join(", ")}`] : []);
            }
        } catch (err) {
            setError(err.message);
        } finally {
            setLoadingResults(false);
        }
    };

    const title = isEarnings ? "Earnings Calendar" : "Market Cap Weights";
    const description = isEarnings
        ? "Load a portfolio or type tickers manually, then scan earnings dates."
        : "Load a portfolio or type tickers manually, then derive market-cap weights.";

    return (
        <Box sx={{ width: "100%", maxWidth: 1280, mx: "auto", px: { xs: 1.5, sm: 3 }, py: 3 }}>
            <Typography variant="h4" sx={{ fontWeight: 700, mb: 0.5 }}>
                {title}
            </Typography>
            <Typography color="text.secondary" sx={{ mb: 2 }}>
                {description}
            </Typography>

            <Paper sx={{ p: { xs: 1.5, sm: 2 }, borderRadius: 2, mb: 2 }}>
                <SourcePicker
                    accounts={accounts}
                    accountId={accountId}
                    setAccountId={setAccountId}
                    onLoad={loadSource}
                    loading={loadingSource}
                />

                {loadingSource && <LinearProgress sx={{ mt: 2 }} />}

                {sourceSummary && (
                    <Typography variant="body2" color="text.secondary" sx={{ mt: 1.5 }}>
                        Loaded {tickers.length} stocks from {sourceSummary.label}
                        {sourceSummary.provider ? ` via ${sourceSummary.provider}` : ""}
                        {sourceSummary.effective_date ? ` as of ${sourceSummary.effective_date}` : ""}.
                    </Typography>
                )}

                <Divider sx={{ my: 2 }} />

                <StockListEditor
                    tickers={tickers}
                    onChange={setTickers}
                    sourceHoldings={sourceHoldings}
                />

                {isEarnings && (
                    <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mt: 2 }}>
                        <TextField
                            size="small"
                            type="date"
                            label="Start"
                            value={startDate}
                            onChange={(event) => setStartDate(event.target.value)}
                            InputLabelProps={{ shrink: true }}
                        />
                        <TextField
                            size="small"
                            type="date"
                            label="End"
                            value={endDate}
                            onChange={(event) => setEndDate(event.target.value)}
                            InputLabelProps={{ shrink: true }}
                        />
                    </Stack>
                )}

                <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 2 }}>
                    <Button variant="contained" onClick={runTool} disabled={!tickers.length || loadingResults}>
                        {isEarnings ? "Load Earnings" : "Calculate Weights"}
                    </Button>
                    <Typography variant="caption" color="text.secondary">
                        {tickers.length} selected
                    </Typography>
                </Stack>
            </Paper>

            {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
            {warnings.map((warning) => (
                <Alert key={warning} severity="warning" sx={{ mb: 1 }}>
                    {warning}
                </Alert>
            ))}

            <Paper sx={{ p: { xs: 1.5, sm: 2 }, borderRadius: 2, overflowX: "auto" }}>
                {loadingResults && <LinearProgress sx={{ mb: 2 }} />}
                {!marketCapData && !earningsData && !loadingResults && (
                    <Typography variant="body2" color="text.secondary">
                        Results will appear here.
                    </Typography>
                )}
                {isEarnings ? (
                    <EarningsResults data={earningsData} />
                ) : (
                    <MarketCapResults data={marketCapData} sourceHoldings={sourceHoldings} />
                )}
            </Paper>
        </Box>
    );
}
