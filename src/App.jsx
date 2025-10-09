import React, { useEffect, useState } from "react";
import {
    AppBar,
    Tabs,
    Tab,
    Toolbar,
    Typography,
    CircularProgress,
    useTheme,
} from "@mui/material";
import AccountTabs from "./components/AccountTabs";

export default function App() {
    const [accounts, setAccounts] = useState([]);
    const [active, setActive] = useState(0);
    const [loading, setLoading] = useState(true);
    const theme = useTheme();

    useEffect(() => {
        fetch("http://127.0.0.1:8000/api/accounts")
            .then((r) => r.json())
            .then((data) => {
                setAccounts(data);
                setLoading(false);
            })
            .catch(() => setLoading(false));
    }, []);

    if (loading) return <CircularProgress sx={{ m: 4 }} />;
    if (!accounts.length)
        return <Typography sx={{ m: 4 }}>No accounts found.</Typography>;

    return (
        <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
            <AppBar position="static" color="primary">
                <Toolbar variant="dense">
                    <Typography variant="h6" sx={{ flexGrow: 1 }}>
                        Portfolio Viewer
                    </Typography>
                </Toolbar>
                <Tabs
                    value={active}
                    onChange={(_, v) => setActive(v)}
                    textColor="inherit"
                    indicatorColor="secondary"
                    variant="scrollable"
                    scrollButtons="auto"
                    allowScrollButtonsMobile
                    sx={{
                        "& .MuiTab-root": {
                            textTransform: "none",
                            minWidth: 160, // keeps tab names readable
                            paddingX: 2,
                            fontWeight: 500,
                            fontSize: "0.95rem",
                        },
                        "& .MuiTabs-scrollButtons": {
                            color: theme.palette.grey[100],
                        },
                    }}
                >
                    {accounts.map((acc) => (
                        <Tab key={acc.id} label={acc.name} />
                    ))}
                </Tabs>
            </AppBar>

            <AccountTabs account={accounts[active]} />
        </div>
    );
}
