import { createTheme } from "@mui/material/styles";

export const THEMES = {
    light: createTheme({
        palette: {
            mode: "light",
            primary: { main: "#1976d2" },
            secondary: { main: "#f50057" },
            background: { default: "#fafafa", paper: "#ffffff" },
            text: { primary: "#111", secondary: "#333" },
        },
    }),

    dark: createTheme({
        palette: {
            mode: "dark",
            primary: { main: "#90caf9" },
            secondary: { main: "#f48fb1" },
            background: { default: "#121212", paper: "#1e1e1e" },
        },
    }),

    // 💼 Professional – Bloomberg-style greys + teal accents
    slate: createTheme({
        palette: {
            mode: "dark",
            primary: { main: "#26a69a" },
            secondary: { main: "#ffca28" },
            background: { default: "#1b1e24", paper: "#23272f" },
            text: { primary: "#e0e0e0", secondary: "#9e9e9e" },
        },
    }),

    // ⚡ Tech – Neon purple/green
    cyber: createTheme({
        palette: {
            mode: "dark",
            primary: { main: "#00e676" },
            secondary: { main: "#00e676" },
            background: { default: "#0a0a0f", paper: "#111116" },
            text: { primary: "#e0e0e0", secondary: "#8e8e8e" },
        },
    }),

    // 🌅 Warm – Sunset gradient feel
    sunrise: createTheme({
        palette: {
            mode: "light",
            primary: { main: "#ff7043" },
            secondary: { main: "#8e24aa" },
            background: { default: "#fff8f5", paper: "#ffffff" },
            text: { primary: "#3e2723", secondary: "#6d4c41" },
        },
    }),
};

