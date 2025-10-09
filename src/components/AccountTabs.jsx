import React, { useState } from "react";
import { Tabs, Tab } from "@mui/material";
import ReportFrame from "./ReportFrame";
import HoldingsTable from "./HoldingsTable";
import TransactionsTable from "./TransactionsTable";

export default function AccountTabs({ account }) {
    const [tab, setTab] = useState("analytics");

    return (
        <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
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

            <div style={{ flex: 1, overflow: "auto", minHeight: 0 }}>
                {tab === "analytics" && (
                    <ReportFrame src={`http://127.0.0.1:8000${account.report}`} />
                )}
                {tab === "holdings" && (
                    <HoldingsTable src={`http://127.0.0.1:8000${account.weights}`} />
                )}
                {tab === "transactions" && (
                    <TransactionsTable src={`http://127.0.0.1:8000${account.trades}`} />
                )}
            </div>
        </div>
    );
}
