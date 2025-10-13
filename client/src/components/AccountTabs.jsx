import React, { useState } from "react";
import { Tabs, Tab, Box } from "@mui/material";
import CSVTable from "./CSVTable.jsx";
import PlotlyDashboard from "./PlotlyDashboard.jsx";

export default function AccountTabs({ account }) {
    const [tab, setTab] = useState("analytics");

    return (
        <Box sx={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
            {/* ===== Inner Tabs Header ===== */}
            <Box
                sx={{
                    position: "sticky",
                    top: 0,
                    zIndex: 1000,
                    backgroundColor: "background.paper",
                    borderBottom: (theme) => `1px solid ${theme.palette.divider}`,
                }}
            >
                <Tabs
                    value={tab}
                    onChange={(_, v) => setTab(v)}
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
                {tab === "holdings" && (
                    <CSVTable src={account.weights} title="Current Portfolio Holdings" />
                )}
                {tab === "transactions" && (
                    <CSVTable src={account.trades} title="Trade History" />
                )}
            </Box>
        </Box>
    );
}
