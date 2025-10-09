import React, { useState } from "react";
import { Tabs, Tab } from "@mui/material";
import ReportFrame from "./ReportFrame";
import CSVTable from "./CSVTable.jsx";

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
                    <CSVTable src={`http://127.0.0.1:8000${account.weights}`} title="Current Portfolio Holdings"/>
                )}
                {tab === "transactions" && (
                    <CSVTable src={`http://127.0.0.1:8000${account.trades}`} title="Trade History"/>
                )}
            </div>
        </div>
    );
}
