// src/components/AccountTabs.jsx
import React, { memo, useEffect, useState } from "react";
import { Tabs, Tab, Box, Typography, Button, Stack } from "@mui/material";
import OpenInNewIcon from "@mui/icons-material/OpenInNew";
import CSVTable from "./CSVTable.jsx";
import PlotlyDashboard from "./PlotlyDashboard.jsx";
import PortfolioAbout from "./PortfolioAbout.jsx";

function umamiTrack(eventName, data) {
    try {
        if (typeof window !== "undefined" && window.umami && typeof window.umami.track === "function") {
            window.umami.track(eventName, data);
        }
    } catch {
        // ignore
    }
}

function AccountTabs({ account, liveStore, embedded = false, onOpenBacksimulator = null }) {
    const [tab, setTab] = useState("analytics");
    const [analyticsHeaderText, setAnalyticsHeaderText] = useState("");
    const [holdingsHeaderText, setHoldingsHeaderText] = useState("");
    const tableTab = tab === "holdings" || tab === "transactions";

    // When account changes, reset inner tab + track
    useEffect(() => {
        if (!account) return;
        setTab("analytics");
        setAnalyticsHeaderText("");
        setHoldingsHeaderText("");
        umamiTrack("account_view_loaded", {
            account_id: account.id,
            account_name: account.name,
            default_tab: "analytics",
        });
    }, [account?.id]); // eslint-disable-line react-hooks/exhaustive-deps

    // Track inner tab change
    useEffect(() => {
        if (!account) return;
        umamiTrack("account_inner_tab_selected", {
            account_id: account.id,
            account_name: account.name,
            tab,
        });
    }, [tab, account?.id]); // eslint-disable-line react-hooks/exhaustive-deps

    const headerText =
        tab === "analytics"
            ? analyticsHeaderText
            : tab === "holdings"
                ? holdingsHeaderText
                : "";
    const canOpenBacksimulator =
        !embedded &&
        Boolean(onOpenBacksimulator) &&
        Boolean(account?.weights) &&
        !account?.disable_live &&
        !account?.disableLive;
    const hasAbout = Boolean(account?.about?.trim());
    const showMetaRow = Boolean(headerText) || hasAbout || canOpenBacksimulator;

    return (
        <Box sx={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0, minWidth: 0 }}>
            {/* ===== Inner Tabs Header ===== */}
            <Box
                sx={{
                    position: embedded ? "static" : "sticky",
                    top: embedded ? "auto" : 0,
                    zIndex: 1000,
                    backgroundColor: "background.paper",
                    minWidth: 0,
                }}
            >
                <Tabs
                    value={tab}
                    onChange={(_, v) => {
                        setTab(v);
                        umamiTrack("account_inner_tab_click", {
                            account_id: account?.id,
                            account_name: account?.name,
                            tab: v,
                        });
                    }}
                    indicatorColor="primary"
                    textColor="primary"
                    variant="fullWidth"
                >
                    <Tab value="analytics" label="Analytics" />
                    <Tab value="holdings" label="Holdings" />
                    <Tab value="transactions" label="Transactions" />
                </Tabs>
            </Box>

            {/* ===== Scrollable Content Area ===== */}
            <Box
                sx={{
                    flex: embedded ? "0 0 auto" : 1,
                    minHeight: 0,
                    minWidth: 0,
                    overflow: embedded ? "visible" : tableTab ? "hidden" : "auto",
                    display: "flex",
                    flexDirection: "column",
                }}
            >
                {showMetaRow && (
                    <Box
                        sx={{
                            px: { xs: 1.5, sm: 2 },
                            pt: 0.75,
                            pb: 0.25,
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "space-between",
                            gap: 1,
                            flexWrap: "wrap",
                        }}
                    >
                        <Box sx={{ minWidth: 0, flex: 1 }}>
                            {headerText ? (
                                <Typography
                                    variant="caption"
                                    sx={{
                                        display: "block",
                                        color: "text.secondary",
                                        textAlign: "left",
                                        whiteSpace: "nowrap",
                                        overflow: "hidden",
                                        textOverflow: "ellipsis",
                                        fontWeight: 500,
                                    }}
                                >
                                    {headerText}
                                </Typography>
                            ) : null}
                        </Box>
                        <Stack direction="row" spacing={0.25} sx={{ flexShrink: 0, alignItems: "center" }}>
                            <PortfolioAbout about={account.about} />
                            {canOpenBacksimulator ? (
                                <Button
                                    size="small"
                                    variant="text"
                                    endIcon={<OpenInNewIcon sx={{ fontSize: 16 }} />}
                                    onClick={() => {
                                        onOpenBacksimulator?.();
                                        umamiTrack("open_backsimulator_click", {
                                            account_id: account?.id,
                                            account_name: account?.name,
                                        });
                                    }}
                                    sx={{
                                        minWidth: 0,
                                        px: 0.75,
                                        py: 0.25,
                                        flexShrink: 0,
                                        color: "text.secondary",
                                        textTransform: "none",
                                        fontSize: "0.78rem",
                                        fontWeight: 500,
                                        whiteSpace: "nowrap",
                                    }}
                                >
                                    Backsim
                                </Button>
                            ) : null}
                        </Stack>
                    </Box>
                )}
                {tab === "analytics" && (
                    <PlotlyDashboard
                        key={account.id}
                        account={account}
                        liveStore={liveStore}
                        onHeaderTextChange={setAnalyticsHeaderText}
                    />
                )}
                {tab === "holdings" && (
                    <CSVTable
                        src={account.weights}
                        title="Current Portfolio Holdings"
                        live
                        liveStore={liveStore}
                        onHeaderTextChange={setHoldingsHeaderText}
                        fillHeight={!embedded}
                    />
                )}
                {tab === "transactions" && <CSVTable src={account.trades} title="Trade History" fillHeight={!embedded} />}
            </Box>
        </Box>
    );
}

export default memo(AccountTabs);
