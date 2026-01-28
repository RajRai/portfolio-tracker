// src/components/AccountTabs.jsx
import React, { useEffect, useState } from "react";
import { Tabs, Tab, Box } from "@mui/material";
import CSVTable from "./CSVTable.jsx";
import PlotlyDashboard from "./PlotlyDashboard.jsx";

function umamiTrack(eventName, data) {
    try {
        if (typeof window !== "undefined" && window.umami && typeof window.umami.track === "function") {
            window.umami.track(eventName, data);
        }
    } catch {
        // ignore
    }
}

export default function AccountTabs({ account }) {
    const [tab, setTab] = useState("analytics");

    // When account changes, reset inner tab + track
    useEffect(() => {
        if (!account) return;
        setTab("analytics");
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

    return (
        <Box sx={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
            {/* ===== Inner Tabs Header ===== */}
            <Box
                sx={{
                    position: "sticky",
                    top: 0,
                    zIndex: 1000,
                    backgroundColor: "background.paper",
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
            <Box sx={{ flex: 1, overflow: "auto", minHeight: 0 }}>
                {tab === "analytics" && <PlotlyDashboard key={account.id} account={account} />}
                {tab === "holdings" && <CSVTable src={account.weights} title="Current Portfolio Holdings" />}
                {tab === "transactions" && <CSVTable src={account.trades} title="Trade History" />}
            </Box>
        </Box>
    );
}
