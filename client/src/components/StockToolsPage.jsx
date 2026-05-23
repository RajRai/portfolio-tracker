import React, { useMemo, useState } from "react";
import {
    Alert,
    Box,
    Button,
    Checkbox,
    Chip,
    Divider,
    LinearProgress,
    Paper,
    Stack,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableRow,
    TextField,
    Typography,
} from "@mui/material";
import { SourcePicker, formatPercent, postJson, splitTickers } from "./toolsShared.jsx";
import { serializeQuery, serializeTickerList, trackToolEvent } from "../umami.js";

const todayString = () => new Date().toISOString().slice(0, 10);

const futureDateString = (days) => {
    const date = new Date();
    date.setDate(date.getDate() + days);
    return date.toISOString().slice(0, 10);
};

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

const marketCapMultipliers = {
    K: 1_000,
    M: 1_000_000,
    MM: 1_000_000,
    MILLION: 1_000_000,
    B: 1_000_000_000,
    BN: 1_000_000_000,
    BILLION: 1_000_000_000,
    T: 1_000_000_000_000,
    TN: 1_000_000_000_000,
    TRILLION: 1_000_000_000_000,
};

const parseMarketCapValue = (value) => {
    const raw = String(value || "").trim();
    if (!raw) return null;

    const compact = raw.toUpperCase().replace(/[$,\s]/g, "");
    const match = compact.match(/^([+-]?(?:\d+(?:\.\d*)?|\.\d+))([A-Z]+)?$/);
    if (!match) return null;

    const amount = Number(match[1]);
    const suffix = match[2] || "";
    const multiplier = suffix ? marketCapMultipliers[suffix] : 1;
    const marketCap = amount * (multiplier || 0);
    return Number.isFinite(marketCap) && marketCap > 0 ? marketCap : null;
};

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

function MarketCapResults({ data, sourceHoldings }) {
    const [included, setIncluded] = useState({});
    const [manualCapInputs, setManualCapInputs] = useState({});
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

        setManualCapInputs((prev) => {
            const next = {};
            const rowTickers = new Set(rows.map((row) => row.ticker));
            for (const [ticker, value] of Object.entries(prev)) {
                if (rowTickers.has(ticker)) {
                    next[ticker] = value;
                }
            }
            return next;
        });
    }, [rows]);

    const { displayRows, includedTotal } = useMemo(() => {
        const rowsWithManualCaps = rows.map((row) => {
            const manualInput = manualCapInputs[row.ticker] || "";
            const manualMarketCap = parseMarketCapValue(manualInput);
            const hasManualInput = Boolean(manualInput.trim());
            const providerMarketCap = row.market_cap ? Number(row.market_cap) : null;
            const effectiveMarketCap = manualMarketCap || providerMarketCap;

            return {
                ...row,
                effective_market_cap: effectiveMarketCap,
                has_manual_input: hasManualInput,
                manual_market_cap: manualMarketCap,
                manual_market_cap_invalid: hasManualInput && manualMarketCap == null,
            };
        });

        const nextIncludedTotal = rowsWithManualCaps.reduce(
            (sum, row) => (
                sum + ((included[row.ticker] ?? true) && row.effective_market_cap ? row.effective_market_cap : 0)
            ),
            0
        );

        const nextDisplayRows = rowsWithManualCaps.map((row) => ({
            ...row,
            adjusted_weight:
                (included[row.ticker] ?? true) && row.effective_market_cap && nextIncludedTotal > 0
                    ? row.effective_market_cap / nextIncludedTotal
                    : 0,
        }));

        return {
            displayRows: nextDisplayRows,
            includedTotal: nextIncludedTotal,
        };
    }, [rows, included, manualCapInputs]);

    if (!data) return null;

    return (
        <Box>
            <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>
                Included market cap: {formatCurrency(includedTotal)}
            </Typography>
            <Table size="small">
                <TableHead>
                <TableRow>
                    <TableCell padding="checkbox">Use</TableCell>
                    <TableCell>Ticker</TableCell>
                    <TableCell>Name</TableCell>
                    <TableCell align="right">Market Cap / Override</TableCell>
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
                                checked={row.effective_market_cap ? included[row.ticker] ?? true : false}
                                onChange={(event) => {
                                    setIncluded((prev) => ({
                                        ...prev,
                                        [row.ticker]: event.target.checked,
                                    }));
                                }}
                                disabled={!row.effective_market_cap}
                            />
                        </TableCell>
                        <TableCell>{row.ticker}</TableCell>
                        <TableCell>{row.name}</TableCell>
                        <TableCell align="right">
                            <TextField
                                size="small"
                                value={manualCapInputs[row.ticker] || ""}
                                onChange={(event) => {
                                    const value = event.target.value;
                                    setManualCapInputs((prev) => ({
                                        ...prev,
                                        [row.ticker]: value,
                                    }));
                                }}
                                placeholder={row.market_cap ? formatCurrency(row.market_cap) : "Enter cap"}
                                error={row.manual_market_cap_invalid}
                                helperText={
                                    row.manual_market_cap_invalid
                                        ? "Use a positive number, e.g. 48B"
                                        : row.has_manual_input
                                            ? `Manual: ${formatCurrency(row.manual_market_cap)}`
                                            : row.market_cap
                                                ? `Provider: ${formatCurrency(row.market_cap)}`
                                                : "No provider cap"
                                }
                                sx={{ minWidth: 170 }}
                            />
                        </TableCell>
                        <TableCell align="right">{formatPercent(row.adjusted_weight)}</TableCell>
                        <TableCell align="right">{formatPercent(sourceWeightByTicker[row.ticker])}</TableCell>
                        <TableCell>
                            {row.has_manual_input && row.manual_market_cap ? "Manual market cap" : row.valuation_method || ""}
                        </TableCell>
                        <TableCell>
                            {row.manual_market_cap_invalid
                                ? "Manual value ignored"
                                : row.has_manual_input && row.manual_market_cap
                                    ? "Manual override"
                                    : row.note || ""}
                        </TableCell>
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
    const toolEventName = isEarnings ? "earnings_calendar" : "market_cap_weights";
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

    const buildSourceQuery = () => ({
        sourceType: "portfolio",
        accountId,
    });

    const buildToolQuery = () => (
        isEarnings
            ? {
                tickers,
                start: startDate,
                end: endDate,
            }
            : {
                tickers,
            }
    );

    const buildToolEventData = (query) => ({
        selected_account_id: accountId || null,
        has_loaded_source: Boolean(sourceSummary),
        source_label: sourceSummary?.label || null,
        source_weight_mode: sourceSummary?.weightSource || null,
        query: serializeQuery(query),
        query_source_type: "portfolio",
        query_account_id: accountId || null,
        query_tickers: serializeTickerList(query?.tickers || []),
        query_ticker_count: (query?.tickers || []).length,
        ...(isEarnings ? {
            query_start_date: query?.start || null,
            query_end_date: query?.end || null,
        } : {}),
    });

    const loadSource = async () => {
        setError("");
        setWarnings([]);
        setLoadingSource(true);
        setMarketCapData(null);
        setEarningsData(null);
        const sourceQuery = buildSourceQuery();

        try {
            const payload = await postJson("/api/tools/stock-source", sourceQuery);
            setTickers(payload.tickers || []);
            setSourceHoldings(payload.holdings || []);
            setSourceSummary(payload.source || null);
            setWarnings(payload.warnings || []);
            trackToolEvent(toolEventName, "source_loaded", {
                query: serializeQuery(sourceQuery),
                query_source_type: sourceQuery.sourceType,
                query_account_id: sourceQuery.accountId || null,
                selected_account_id: accountId || null,
                loaded_tickers: serializeTickerList(payload.tickers || []),
                ticker_count: (payload.tickers || []).length,
                warnings_count: (payload.warnings || []).length,
                source_weight_mode: payload.source?.weightSource || "current",
            });
        } catch (err) {
            setError(err.message);
            trackToolEvent(toolEventName, "source_load_failed", {
                query: serializeQuery(sourceQuery),
                query_source_type: sourceQuery.sourceType,
                query_account_id: sourceQuery.accountId || null,
                selected_account_id: accountId || null,
                error: err.message,
            });
        } finally {
            setLoadingSource(false);
        }
    };

    const runTool = async () => {
        setError("");
        setWarnings([]);
        setLoadingResults(true);
        const toolQuery = buildToolQuery();
        const baseEventData = buildToolEventData(toolQuery);

        trackToolEvent(toolEventName, "run_started", {
            ...baseEventData,
        });

        try {
            if (isEarnings) {
                const payload = await postJson("/api/tools/earnings-calendar", toolQuery);
                setEarningsData(payload);
                setWarnings(payload.warnings || []);
                trackToolEvent(toolEventName, "run_completed", {
                    ...baseEventData,
                    event_count: (payload.events || []).length,
                    warnings_count: (payload.warnings || []).length,
                });
            } else {
                const payload = await postJson("/api/tools/market-cap-weights", toolQuery);
                setMarketCapData(payload);
                setWarnings(payload.warnings || []);
                trackToolEvent(toolEventName, "run_completed", {
                    ...baseEventData,
                    row_count: (payload.rows || []).length,
                    market_cap_count: (payload.rows || []).filter((row) => Boolean(row.market_cap)).length,
                    warnings_count: (payload.warnings || []).length,
                });
            }
        } catch (err) {
            setError(err.message);
            trackToolEvent(toolEventName, "run_failed", {
                ...baseEventData,
                error: err.message,
            });
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
