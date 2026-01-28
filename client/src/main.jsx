import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import {allPresets, ThemeManagerProvider} from "@rajrai/mui-theme-manager";

function Root() {
    return (
        <ThemeManagerProvider presets={allPresets}>
            <App />
        </ThemeManagerProvider>
    );
}

ReactDOM.createRoot(document.getElementById("root")).render(<Root />);
