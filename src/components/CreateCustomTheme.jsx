import React, { useState } from "react";
import {
    Dialog, DialogTitle, DialogContent, DialogActions,
    Button, TextField, Box, Typography,
} from "@mui/material";
import { saveCustomTheme } from "../themes/themeManager.js";

export default function CustomThemeDialog({ open, onClose, refresh }) {
    const [name, setName] = useState("");
    const [primary, setPrimary] = useState("#1976d2");
    const [secondary, setSecondary] = useState("#f50057");
    const [mode, setMode] = useState("light");

    const handleSave = () => {
        if (!name.trim()) return;
        const themeConfig = {
            palette: {
                mode,
                primary: { main: primary },
                secondary: { main: secondary },
                background:
                    mode === "dark"
                        ? { default: "#121212", paper: "#1e1e1e" }
                        : { default: "#fafafa", paper: "#ffffff" },
            },
        };
        saveCustomTheme(name, themeConfig);
        refresh();
        onClose();
    };

    return (
        <Dialog open={open} onClose={onClose}>
            <DialogTitle>Create Custom Theme</DialogTitle>
            <DialogContent>
                <Typography variant="body2" sx={{ mb: 2 }}>
                    Choose your colors and mode.
                </Typography>
                <Box sx={{ display: "flex", flexDirection: "column", gap: 2 }}>
                    <TextField
                        label="Theme Name"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        variant="outlined"
                    />
                    <Box sx={{ display: "flex", gap: 2 }}>
                        <TextField
                            label="Primary Color"
                            type="color"
                            value={primary}
                            onChange={(e) => setPrimary(e.target.value)}
                            sx={{ flex: 1 }}
                        />
                        <TextField
                            label="Secondary Color"
                            type="color"
                            value={secondary}
                            onChange={(e) => setSecondary(e.target.value)}
                            sx={{ flex: 1 }}
                        />
                    </Box>
                    <Box sx={{ display: "flex", gap: 2 }}>
                        <Button
                            variant={mode === "light" ? "contained" : "outlined"}
                            onClick={() => setMode("light")}
                            fullWidth
                        >
                            Light
                        </Button>
                        <Button
                            variant={mode === "dark" ? "contained" : "outlined"}
                            onClick={() => setMode("dark")}
                            fullWidth
                        >
                            Dark
                        </Button>
                    </Box>
                </Box>
            </DialogContent>
            <DialogActions>
                <Button onClick={onClose}>Cancel</Button>
                <Button onClick={handleSave} variant="contained">Save</Button>
            </DialogActions>
        </Dialog>
    );
}
