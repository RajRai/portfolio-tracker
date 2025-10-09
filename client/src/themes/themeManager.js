import { createTheme } from "@mui/material/styles";
import { THEMES } from "./themes";

// Load themes (default + user-defined)
export const loadThemes = () => {
    try {
        const stored = localStorage.getItem("customThemes");
        const parsed = stored ? JSON.parse(stored) : {};
        // rebuild all loaded custom themes into MUI theme objects
        const rebuilt = Object.fromEntries(
            Object.entries(parsed).map(([name, config]) => [name, createTheme(config)])
        );
        return { ...THEMES, ...rebuilt };
    } catch {
        return { ...THEMES };
    }
};

// Save new theme to localStorage (store only raw config)
export const saveCustomTheme = (name, config) => {
    const existing = JSON.parse(localStorage.getItem("customThemes") || "{}");
    existing[name] = config; // <- store the plain config, NOT createTheme(config)
    localStorage.setItem("customThemes", JSON.stringify(existing));
};

// Remember last theme name
export const loadLastTheme = () => localStorage.getItem("lastTheme") || "slate";
export const saveLastTheme = (name) => localStorage.setItem("lastTheme", name);
