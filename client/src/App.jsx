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
    IconButton,
    Tooltip,
} from "@mui/material";
import Menu from "@mui/material/Menu";
import AddIcon from "@mui/icons-material/Add";
import GitHubIcon from "@mui/icons-material/GitHub";
import MoreVertIcon from "@mui/icons-material/MoreVert";
import CustomThemeDialog from "./components/CreateCustomTheme.jsx";
import AccountTabs from "./components/AccountTabs.jsx";

export default function App({ themeName, setThemeName, themes, refreshThemes }) {
    const [accounts, setAccounts] = useState([]);
    const [active, setActive] = useState(0);
    const [loading, setLoading] = useState(true);
    const [open, setOpen] = useState(false);
    const theme = useTheme();

    useEffect(() => {
        fetch("/api/accounts")
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
        <Box sx={{ display: "flex", flexDirection: "column", height: "100dvh" }}>
            {/* ======= AppBar ======= */}
            <AppBar position="static" color="primary">
                <Toolbar
                    variant="dense"
                    sx={{
                        justifyContent: "space-between",
                        minHeight: 40,
                        px: 1.5,
                        overflow: "hidden",
                    }}
                >
                    {/* ===== Account Tabs ===== */}
                    <Tabs
                        value={active}
                        onChange={(_, v) => setActive(v)}
                        textColor="inherit"
                        indicatorColor="secondary"
                        variant="scrollable"
                        scrollButtons="auto"
                        allowScrollButtonsMobile
                        sx={{
                            minHeight: 36,
                            flex: 1, // allow tabs to shrink gracefully
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
                        {accounts.map((acc) => (
                            <Tab key={acc.id} label={acc.name} />
                        ))}
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
                        <Select
                            value={themeName}
                            onChange={(e) => setThemeName(e.target.value)}
                            size="small"
                            variant="outlined"
                            sx={{
                                color: "white",
                                fontSize: "0.8rem",
                                height: 30,
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
                            startIcon={<AddIcon sx={{ fontSize: 16 }} />}
                            onClick={() => setOpen(true)}
                            sx={{
                                borderColor: "rgba(255,255,255,0.4)",
                                textTransform: "none",
                                fontSize: "0.75rem",
                                lineHeight: 1.2,
                                py: 0.3,
                                "&:hover": { borderColor: "white" },
                            }}
                        >
                            New Theme
                        </Button>

                        {/* GitHub Link */}
                        <Tooltip title="View on GitHub">
                            <IconButton
                                color="inherit"
                                size="small"
                                href="https://github.com/RajRai/portfolio-tracker"
                                target="_blank"
                                rel="noopener noreferrer"
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
                        <MobileMenu
                            themeName={themeName}
                            setThemeName={setThemeName}
                            themes={themes}
                            onOpenNewTheme={() => setOpen(true)}
                        />
                    </Box>
                </Toolbar>
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

function MobileMenu({ themeName, setThemeName, themes, onOpenNewTheme }) {
    const [anchorEl, setAnchorEl] = useState(null);
    const open = Boolean(anchorEl);

    return (
        <>
            <IconButton
                color="inherit"
                size="small"
                onClick={(e) => setAnchorEl(e.currentTarget)}
            >
                <MoreVertIcon />
            </IconButton>
            <Menu
                anchorEl={anchorEl}
                open={open}
                onClose={() => setAnchorEl(null)}
                transformOrigin={{ horizontal: "right", vertical: "top" }}
                anchorOrigin={{ horizontal: "right", vertical: "bottom" }}
            >
                {/* Theme selector */}
                <Box
                    sx={{
                        px: 2,
                        py: 1,
                        display: "flex",
                        alignItems: "center",
                        gap: 1,
                        color: "text.primary",
                    }}
                >
                    <Typography variant="body2" sx={{ minWidth: 50 }}>
                        Theme:
                    </Typography>
                    <Select
                        value={themeName}
                        onChange={(e) => {
                            setThemeName(e.target.value);
                            setAnchorEl(null);
                        }}
                        size="small"
                        variant="outlined"
                        sx={{
                            fontSize: "0.85rem",
                            minWidth: 120,
                            "& .MuiSelect-icon": { fontSize: 18 },
                        }}
                    >
                        {Object.keys(themes).map((name) => (
                            <MenuItem key={name} value={name}>
                                {name.charAt(0).toUpperCase() + name.slice(1)}
                            </MenuItem>
                        ))}
                    </Select>
                </Box>

                <MenuItem
                    onClick={() => {
                        onOpenNewTheme();
                        setAnchorEl(null);
                    }}
                >
                    <AddIcon fontSize="small" sx={{ mr: 1 }} />
                    New Theme
                </MenuItem>

                <MenuItem
                    component="a"
                    href="https://github.com/RajRai/portfolio-tracker"
                    target="_blank"
                    rel="noopener noreferrer"
                >
                    <GitHubIcon fontSize="small" sx={{ mr: 1 }} />
                    View on GitHub
                </MenuItem>
            </Menu>
        </>
    );
}
