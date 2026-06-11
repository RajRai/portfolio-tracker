import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import {allPresets, ThemeManagerProvider} from "@rajrai/mui-theme-manager";
import { bootAnalytics } from "./umami.js";

void bootAnalytics();

function Root() {
    return (
        <ThemeManagerProvider presets={allPresets}>
            <App />
        </ThemeManagerProvider>
    );
}

ReactDOM.createRoot(document.getElementById("root")).render(<Root />);
