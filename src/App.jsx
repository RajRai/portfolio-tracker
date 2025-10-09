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
    Select,
    Button,
    MenuItem,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import CustomThemeDialog from "./components/CreateCustomTheme.jsx";
import AccountTabs from "./components/AccountTabs.jsx";

export default function App({ themeName, setThemeName, themes, refreshThemes }) {
    const [accounts, setAccounts] = useState([]);
    const [active, setActive] = useState(0);
    const [loading, setLoading] = useState(true);
    const [open, setOpen] = useState(false);
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
        <Box sx={{ display: "flex", flexDirection: "column", height: "100vh" }}>
            {/* ======= AppBar ======= */}
            <AppBar position="static" color="primary">
                <Toolbar variant="dense" sx={{ justifyContent: "space-between" }}>
                    <Typography variant="h6">Portfolio Viewer</Typography>

                    <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
                        {/* Theme Picker */}
                        <Select
                            value={themeName}
                            onChange={(e) => setThemeName(e.target.value)}
                            size="small"
                            variant="outlined"
                            sx={{
                                color: "white",
                                ".MuiSvgIcon-root": { color: "white" },
                                bgcolor: "rgba(255,255,255,0.1)",
                                "& fieldset": { border: "none" },
                            }}
                        >
                            {Object.keys(themes).map((name) => (
                                <MenuItem key={name} value={name}>
                                    {name.charAt(0).toUpperCase() + name.slice(1)}
                                </MenuItem>
                            ))}
                        </Select>

                        {/* New Theme Button */}
                        <Button
                            color="inherit"
                            variant="outlined"
                            size="small"
                            startIcon={<AddIcon />}
                            onClick={() => setOpen(true)}
                            sx={{
                                borderColor: "rgba(255,255,255,0.4)",
                                textTransform: "none",
                                "&:hover": { borderColor: "white" },
                            }}
                        >
                            New Theme
                        </Button>
                    </Box>
                </Toolbar>

                {/* ======= Account Tabs ======= */}
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
                            minWidth: 160,
                            paddingX: 2,
                            fontWeight: 500,
                            fontSize: "0.95rem",
                        },
                    }}
                >
                    {accounts.map((acc) => (
                        <Tab key={acc.id} label={acc.name} />
                    ))}
                </Tabs>
            </AppBar>

            {/* ======= Main Account View ======= */}
            <Box sx={{ flex: 1, overflow: "auto", bgcolor: theme.palette.background.default }}>
                <AccountTabs account={accounts[active]} />
            </Box>

            {/* ======= Custom Theme Dialog ======= */}
            <CustomThemeDialog
                open={open}
                onClose={() => setOpen(false)}
                refresh={refreshThemes}
            />
        </Box>
    );
}
