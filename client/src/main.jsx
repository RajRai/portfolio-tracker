import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import {allPresets, ThemeManagerProvider} from "@rajrai/mui-theme-manager";
import {THEMES} from "./themes.js";

function Root() {
    const presets = Object.keys(THEMES).map(key => {
        const value = THEMES[key];
        return {
            id: key,
            name: key.charAt(0).toUpperCase() + key.slice(1),
            themeOptions: value,
            isPreset: true
        }
    });

    return (
        <ThemeManagerProvider presets={presets}>
            <App />
        </ThemeManagerProvider>
    );
}

ReactDOM.createRoot(document.getElementById("root")).render(<Root />);
