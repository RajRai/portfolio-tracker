import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import { ThemeProvider, CssBaseline } from "@mui/material";
import { loadThemes, loadLastTheme, saveLastTheme } from "./themes/themeManager.js";

function Root() {
    const [themeName, setThemeName] = React.useState(loadLastTheme());
    const [themes, setThemes] = React.useState(loadThemes());

    const theme = themes[themeName] || themes.slate;

    const handleSetTheme = (name) => {
        setThemeName(name);
        saveLastTheme(name);
    };

    const refreshThemes = () => setThemes(loadThemes());

    return (
        <ThemeProvider theme={theme}>
            <CssBaseline />
            <App
                themeName={themeName}
                setThemeName={handleSetTheme}
                themes={themes}
                refreshThemes={refreshThemes}
            />
        </ThemeProvider>
    );
}

ReactDOM.createRoot(document.getElementById("root")).render(<Root />);
