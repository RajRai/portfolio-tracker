import { createTheme } from "@mui/material/styles";
import { THEMES } from "./themes";

// Load themes (default + user-defined)
export const loadThemes = () => {
    try {
        const stored = localStorage.getItem("customThemes");
        const parsed = stored ? JSON.parse(stored) : {};
        return { ...THEMES, ...parsed };
    } catch {
        return { ...THEMES };
    }
};

// Save new theme to localStorage
export const saveCustomTheme = (name, config) => {
    const existing = JSON.parse(localStorage.getItem("customThemes") || "{}");
    existing[name] = createTheme(config);
    localStorage.setItem("customThemes", JSON.stringify(existing));
};

// Remember last theme name
export const loadLastTheme = () => localStorage.getItem("lastTheme") || "slate";
export const saveLastTheme = (name) => localStorage.setItem("lastTheme", name);
