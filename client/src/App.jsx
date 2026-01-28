// src/App.jsx
import React, { useEffect, useState } from "react";
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
    MenuItem,
} from "@mui/material";
import Menu from "@mui/material/Menu";
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

export default function App() {
    const [accounts, setAccounts] = useState([]);
    const [active, setActive] = useState(0);
    const [loading, setLoading] = useState(true);
    const theme = useTheme();

    useEffect(() => {
        fetch("/api/accounts")
            .then((r) => r.json())
            .then(async (data) => {
                const enriched = await Promise.all(
                    data.map(async (acc) => {
                        try {
                            const url = acc.report?.replace(".html", "_interactive.json");
                            const j = url ? await (await fetch(url)).json() : null;
                            const daily = j?.portfolio?.daily;
                            const last = Array.isArray(daily) && daily.length ? daily[daily.length - 1].v : null;
                            return { ...acc, dailyReturn: last };
                        } catch {
                            return { ...acc, dailyReturn: null };
                        }
                    })
                );

                setAccounts(enriched);
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
                            const val = acc.dailyReturn;
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
                                onChange: (e) => {
                                    // ThemeSelector will handle the change internally; we just track it.
                                    umamiTrack("theme_selected", { theme_id: e?.target?.value });
                                },
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
                                onClick: () => umamiTrack("new_theme_button_click", { location: "appbar_desktop" }),
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
                <AccountTabs account={accounts[active]} />
            </Box>
        </Box>
    );
}

function MobileMenu() {
    const [anchorEl, setAnchorEl] = useState(null);
    const open = Boolean(anchorEl);
    const { onEditTheme, activeTheme } = useThemeManager();

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
                onClose={() => {
                    setAnchorEl(null);
                    umamiTrack("mobile_menu_close", {});
                }}
                transformOrigin={{ horizontal: "right", vertical: "top" }}
                anchorOrigin={{ horizontal: "right", vertical: "bottom" }}
            >
                {/* Theme selector */}
                <ThemeSelector
                    selectProps={{
                        size: "small",
                        variant: "outlined",
                        onChange: (e) => {
                            umamiTrack("theme_selected", { theme_id: e?.target?.value, location: "mobile_menu" });
                        },
                        sx: {
                            fontSize: "0.85rem",
                            minWidth: 120,
                            "& .MuiSelect-icon": { fontSize: 18 },
                        },
                    }}
                />

                <MenuItem
                    onClick={() => {
                        setAnchorEl(null);

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
                    onClick={() =>
                        umamiTrack("github_click", { location: "mobile_menu", href: "portfolio-tracker" })
                    }
                >
                    <GitHubIcon fontSize="small" sx={{ mr: 1 }} />
                    View on GitHub
                </MenuItem>
            </Menu>
        </>
    );
}
