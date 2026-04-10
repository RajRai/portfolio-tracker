// src/App.jsx
import React, { useEffect, useMemo, useRef, useState } from "react";
import {
    AppBar,
    Tabs,
    Tab,
    Toolbar,
    Typography,
    CircularProgress,
    useTheme,
    Box,
    IconButton,
    Tooltip,
    ListSubheader,
    MenuItem,
} from "@mui/material";
import Menu from "@mui/material/Menu";
import Papa from "papaparse";
import CheckIcon from "@mui/icons-material/Check";
import GitHubIcon from "@mui/icons-material/GitHub";
import MoreVertIcon from "@mui/icons-material/MoreVert";
import AccountTabs from "./components/AccountTabs.jsx";
import { ThemeSelector, NewThemeButton, ThemeEditorModal, useThemeManager } from "@rajrai/mui-theme-manager";
import { deepClone } from "@mui/x-data-grid/internals";

function umamiTrack(eventName, data) {
    // Umami is typically exposed as window.umami.track(...)
    // Make this a no-op if Umami isn't loaded (e.g., dev).
    try {
        if (typeof window !== "undefined" && window.umami && typeof window.umami.track === "function") {
            window.umami.track(eventName, data);
        }
    } catch {
        // ignore
    }
}

const toNum = (v) => {
    if (v == null) return NaN;
    const s = String(v).replace(/[,$%]/g, "").trim();
    const n = Number(s);
    return isNaN(n) ? NaN : n;
};

const parseLiveHoldings = (csvText) =>
    Papa.parse(csvText, { header: true }).data
        .filter((row) => row && Object.values(row).some((v) => v?.trim()))
        .map((row) => ({
            ticker: row.Ticker?.trim(),
            quantity: toNum(row._Quantity),
        }))
        .filter((row) => row.ticker && !isNaN(row.quantity) && row.quantity > 0);

const POLL_LIVE_MESSAGE = "Live prices: updating every 5 seconds";
const STREAM_LIVE_MESSAGE = "Live prices: updating live";
const CONNECTING_LIVE_MESSAGE = "Live prices: connecting";

export default function App() {
    const [accounts, setAccounts] = useState([]);
    const [liveConfigs, setLiveConfigs] = useState([]);
    const [accountDailyReturns, setAccountDailyReturns] = useState({});
    const [active, setActive] = useState(0);
    const [loading, setLoading] = useState(true);
    const theme = useTheme();
    const quotesRef = useRef({});
    const liveStore = useMemo(() => {
        let snapshot = {
            status: "off",
            message: "",
            quotes: {},
        };
        const listeners = new Set();

        const emit = () => {
            listeners.forEach((listener) => listener());
        };

        return {
            getSnapshot: () => snapshot,
            subscribe: (listener) => {
                listeners.add(listener);
                return () => listeners.delete(listener);
            },
            publish: (next) => {
                snapshot = typeof next === "function" ? next(snapshot) : next;
                emit();
            },
        };
    }, []);

    useEffect(() => {
        fetch("/api/accounts")
            .then((r) => r.json())
            .then(async (data) => {
                const enriched = await Promise.all(
                    data.map(async (acc) => {
                        try {
                            const url = acc.report?.replace(".html", "_interactive.json");
                            const [j, weightsText] = await Promise.all([
                                url ? (await fetch(url)).json() : null,
                                acc.weights ? await (await fetch(acc.weights)).text() : "",
                            ]);
                            const daily = j?.portfolio?.daily;
                            const last = Array.isArray(daily) && daily.length ? daily[daily.length - 1].v : null;
                            return {
                                ...acc,
                                dailyReturn: last,
                                liveHoldings: parseLiveHoldings(weightsText),
                                benchmarkTicker: j?.benchmark?.ticker || "SPY",
                            };
                        } catch {
                            return {
                                ...acc,
                                dailyReturn: null,
                                liveHoldings: [],
                                benchmarkTicker: "SPY",
                            };
                        }
                    })
                );

                setAccounts(
                    enriched.map(({ liveHoldings, ...acc }) => acc)
                );
                setLiveConfigs(
                    enriched.map(({ id, liveHoldings, benchmarkTicker }) => ({
                        id,
                        liveHoldings,
                        benchmarkTicker,
                    }))
                );
                setAccountDailyReturns(
                    Object.fromEntries(
                        enriched.map(({ id, dailyReturn }) => [id, dailyReturn])
                    )
                );
                setLoading(false);

                umamiTrack("accounts_loaded", {
                    count: enriched.length,
                });
            })
            .catch(() => {
                setLoading(false);
                umamiTrack("accounts_load_failed", {});
            });
    }, []);

    useEffect(() => {
        if (!liveConfigs.length) return;

        const configById = Object.fromEntries(
            liveConfigs.map((config) => [config.id, config])
        );
        const tickers = [...new Set(
            liveConfigs.flatMap((config) => [
                ...config.liveHoldings.map((holding) => holding.ticker),
                config.benchmarkTicker,
            ])
        )];

        if (!tickers.length) return;

        quotesRef.current = {};
        liveStore.publish({
            status: "connecting",
            message: CONNECTING_LIVE_MESSAGE,
            quotes: quotesRef.current,
        });

        const updateAccountReturns = () => {
            setAccountDailyReturns((prev) => {
                let changed = false;
                const next = { ...prev };

                for (const [accountId, config] of Object.entries(configById)) {
                    if (!config?.liveHoldings?.length) continue;

                    let prevCloseValue = 0;
                    let liveValue = 0;

                    for (const holding of config.liveHoldings) {
                        const quote = quotesRef.current[holding.ticker];
                        const prevClose = toNum(quote?.prev_close);
                        const price = toNum(quote?.price);
                        if (isNaN(prevClose) || prevClose <= 0) continue;
                        const livePrice = !isNaN(price) && price > 0 ? price : prevClose;

                        prevCloseValue += holding.quantity * prevClose;
                        liveValue += holding.quantity * livePrice;
                    }

                    if (prevCloseValue <= 0) continue;

                    const nextDailyReturn = liveValue / prevCloseValue - 1;
                    if (next[accountId] !== nextDailyReturn) {
                        next[accountId] = nextDailyReturn;
                        changed = true;
                    }
                }

                return changed ? next : prev;
            });
        };

        const eventSource = new EventSource(
            `/api/live/stocks/stream?tickers=${encodeURIComponent(tickers.join(","))}`
        );

        eventSource.onmessage = (event) => {
            const payload = JSON.parse(event.data);
            if (payload.type === "status") {
                if (payload.transport === "stream") {
                    liveStore.publish((prev) => ({
                        ...prev,
                        status: "stream",
                        message: STREAM_LIVE_MESSAGE,
                    }));
                } else if (payload.transport === "poll") {
                    liveStore.publish((prev) => ({
                        ...prev,
                        status: "poll",
                        message: POLL_LIVE_MESSAGE,
                    }));
                } else {
                    liveStore.publish((prev) => ({
                        ...prev,
                        status: "off",
                        message: payload.message || "",
                    }));
                }
                return;
            }

            if (!payload.quotes) return;

            for (const [ticker, quote] of Object.entries(payload.quotes)) {
                quotesRef.current[ticker] = {
                    ...quotesRef.current[ticker],
                    ...quote,
                };
            }

            if (payload.transport === "stream") {
                liveStore.publish({
                    status: "stream",
                    message: STREAM_LIVE_MESSAGE,
                    quotes: quotesRef.current,
                });
            } else if (payload.transport === "poll") {
                liveStore.publish({
                    status: "poll",
                    message: POLL_LIVE_MESSAGE,
                    quotes: quotesRef.current,
                });
            } else {
                liveStore.publish((prev) => ({
                    ...prev,
                    quotes: quotesRef.current,
                }));
            }

            updateAccountReturns();
        };

        eventSource.onerror = () => {
            liveStore.publish((prev) =>
                prev.status === "poll"
                    ? prev
                    : {
                        ...prev,
                        status: "reconnecting",
                        message: "Live prices: reconnecting",
                    }
            );
        };

        return () => {
            eventSource.close();
        };
    }, [liveConfigs, liveStore]);

    // Track account switching
    useEffect(() => {
        if (!accounts.length) return;
        const acc = accounts[active];
        if (!acc) return;

        umamiTrack("account_selected", {
            account_id: acc.id,
            account_name: acc.name,
            index: active,
        });
    }, [active, accounts]);

    if (loading) return <CircularProgress sx={{ m: 4 }} />;
    if (!accounts.length) return <Typography sx={{ m: 4 }}>No accounts found.</Typography>;

    return (
        <Box sx={{ display: "flex", flexDirection: "column", height: "100dvh" }}>
            <ThemeEditorModal />

            {/* ======= AppBar ======= */}
            <AppBar position="static" color="primary" style={{ borderRadius: 0 }}>
                <Toolbar
                    variant="dense"
                    sx={{
                        justifyContent: "space-between",
                        minHeight: 40,
                        px: 1.5,
                        overflow: "hidden",
                        borderRadius: 0,
                    }}
                >
                    {/* ===== Account Tabs ===== */}
                    <Tabs
                        value={active}
                        onChange={(_, v) => {
                            setActive(v);

                            const acc = accounts?.[v];
                            umamiTrack("account_tab_click", {
                                account_id: acc?.id,
                                account_name: acc?.name,
                                index: v,
                            });
                        }}
                        textColor="inherit"
                        indicatorColor="secondary"
                        variant="scrollable"
                        scrollButtons="auto"
                        allowScrollButtonsMobile
                        sx={{
                            minHeight: 36,
                            flex: 1,
                            "& .MuiTab-root": {
                                textTransform: "none",
                                minWidth: 120,
                                px: 1.5,
                                py: 0.2,
                                fontWeight: 500,
                                fontSize: "0.8rem",
                                minHeight: 36,
                            },
                            "& .MuiTabs-indicator": { height: 2 },
                        }}
                    >
                        {accounts.map((acc) => {
                            const val = accountDailyReturns[acc.id];
                            const color =
                                val == null
                                    ? theme.palette.text.secondary
                                    : val > 0
                                        ? theme.palette.success.light
                                        : val < 0
                                            ? theme.palette.error.light
                                            : theme.palette.text.secondary;
                            const text = val == null ? "" : `${val > 0 ? "+" : ""}${(val * 100).toFixed(2)}%`;

                            return (
                                <Tab
                                    key={acc.id}
                                    label={
                                        <Box
                                            sx={{
                                                display: "flex",
                                                flexDirection: "column",
                                                alignItems: "center",
                                                lineHeight: 1.1,
                                            }}
                                        >
                                            <Typography
                                                sx={{
                                                    fontSize: "0.8rem",
                                                    fontWeight: 500,
                                                    color: "inherit",
                                                }}
                                            >
                                                {acc.name}
                                            </Typography>
                                            {text && (
                                                <Typography
                                                    sx={{
                                                        fontSize: "0.7rem",
                                                        color,
                                                        mt: 0.2,
                                                    }}
                                                >
                                                    {text}
                                                </Typography>
                                            )}
                                        </Box>
                                    }
                                />
                            );
                        })}
                    </Tabs>

                    {/* ===== Desktop controls ===== */}
                    <Box
                        sx={{
                            display: { xs: "none", sm: "flex" },
                            alignItems: "center",
                            gap: 1,
                            flexShrink: 0,
                        }}
                    >
                        {/* Theme Picker */}
                        <ThemeSelector
                            selectProps={{
                                size: "small",
                                variant: "outlined",
                                sx: {
                                    fontSize: "0.8rem",
                                    height: 30,
                                    bgcolor: "rgba(255,255,255,0.1)",
                                    "& fieldset": { border: "none" },
                                },
                            }}
                        />

                        {/* New Theme Button */}
                        <NewThemeButton
                            buttonProps={{
                                color: "inherit",
                            }}
                        />

                        {/* GitHub Link */}
                        <Tooltip title="View on GitHub">
                            <IconButton
                                color="inherit"
                                size="small"
                                href="https://github.com/RajRai/portfolio-tracker"
                                target="_blank"
                                rel="noopener noreferrer"
                                onClick={() =>
                                    umamiTrack("github_click", { location: "appbar_desktop", href: "portfolio-tracker" })
                                }
                                sx={{
                                    p: 0.25,
                                    "& svg": { fontSize: 18 },
                                    "&:hover": { color: "#ddd" },
                                }}
                            >
                                <GitHubIcon />
                            </IconButton>
                        </Tooltip>
                    </Box>

                    {/* ===== Mobile dropdown ===== */}
                    <Box sx={{ display: { xs: "flex", sm: "none" }, flexShrink: 0 }}>
                        <MobileMenu />
                    </Box>
                </Toolbar>
            </AppBar>

            {/* ======= Main Account View ======= */}
            <Box
                sx={{
                    flex: 1,
                    overflow: "auto",
                    bgcolor: theme.palette.background.default,
                }}
            >
                <AccountTabs account={accounts[active]} liveStore={liveStore} />
            </Box>
        </Box>
    );
}

function MobileMenu() {
    const [anchorEl, setAnchorEl] = useState(null);
    const open = Boolean(anchorEl);
    const { onEditTheme, activeTheme, presets, customThemes, activeThemeId, setActiveTheme } = useThemeManager();
    const themes = [...presets, ...customThemes];

    const handleClose = () => {
        setAnchorEl(null);
        umamiTrack("mobile_menu_close", {});
    };

    return (
        <>
            <IconButton
                color="inherit"
                size="small"
                onClick={(e) => {
                    setAnchorEl(e.currentTarget);
                    umamiTrack("mobile_menu_open", {});
                }}
            >
                <MoreVertIcon />
            </IconButton>
            <Menu
                anchorEl={anchorEl}
                open={open}
                onClose={handleClose}
                transformOrigin={{ horizontal: "right", vertical: "top" }}
                anchorOrigin={{ horizontal: "right", vertical: "bottom" }}
                MenuListProps={{ dense: true }}
            >
                <ListSubheader disableSticky sx={{ lineHeight: 1.8 }}>
                    Theme
                </ListSubheader>
                {themes.map((themeOption) => (
                    <MenuItem
                        key={themeOption.id}
                        selected={themeOption.id === activeThemeId}
                        onClick={() => {
                            setActiveTheme(themeOption.id);
                            umamiTrack("theme_selected", {
                                theme_id: themeOption.id,
                                location: "mobile_menu",
                            });
                            handleClose();
                        }}
                        sx={{
                            gap: 1,
                            minWidth: 180,
                            fontWeight: themeOption.id === activeThemeId ? 600 : 400,
                        }}
                    >
                        <Box
                            sx={{
                                width: 18,
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                                color: "primary.main",
                            }}
                        >
                            {themeOption.id === activeThemeId ? <CheckIcon fontSize="small" /> : null}
                        </Box>
                        <Typography variant="inherit" noWrap>
                            {themeOption.name}
                        </Typography>
                    </MenuItem>
                ))}

                <MenuItem
                    onClick={() => {
                        handleClose();

                        const newThemeId = `custom-${Date.now()}`;
                        umamiTrack("new_theme_menuitem_click", { location: "mobile_menu" });

                        onEditTheme(
                            {
                                id: newThemeId,
                                name: "",
                                isPreset: false,
                                themeOptions: deepClone(activeTheme.themeOptions),
                            },
                            undefined
                        );
                    }}
                >
                    New Theme
                </MenuItem>

                <MenuItem
                    component="a"
                    href="https://github.com/RajRai/portfolio-tracker"
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={() => {
                        handleClose();
                        umamiTrack("github_click", { location: "mobile_menu", href: "portfolio-tracker" });
                    }}
                >
                    <GitHubIcon fontSize="small" sx={{ mr: 1 }} />
                    View on GitHub
                </MenuItem>
            </Menu>
        </>
    );
}
