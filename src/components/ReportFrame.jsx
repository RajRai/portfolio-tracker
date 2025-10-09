import React, { useEffect, useState } from "react";
import { useTheme } from "@mui/material/styles";

export default function ReportFrame({ src }) {
    const [html, setHtml] = useState("");
    const theme = useTheme();

    useEffect(() => {
        fetch(src)
            .then((r) => r.text())
            .then(setHtml)
            .catch(console.error);
    }, [src]);

    if (!html) return <div style={{ padding: 16 }}>Loading report...</div>;

    // Theme overrides for QuantStats HTML
    const overrideCSS = `
    html, body {
      background-color: ${theme.palette.background.default} !important;
      color: ${theme.palette.text.primary} !important;
    }

    h1, h2, h3, h4, h5, h6 {
      color: ${theme.palette.text.primary} !important;
    }

    a {
      color: ${theme.palette.primary.main} !important;
    }

    table {
      border-collapse: collapse !important;
      width: 100% !important;
      background-color: transparent !important;
    }

    th, td {
      border: 1px solid ${theme.palette.divider} !important;
      color: ${theme.palette.text.primary} !important;
      background: transparent !important;
    }

    th {
      background-color: ${theme.palette.action.hover} !important;
      color: ${theme.palette.text.primary} !important;
      font-weight: 600 !important;
    }

    tr:nth-of-type(even) td {
      background-color: ${theme.palette.action.selected} !important;
    }
  `;

    // Inject <style> tag before </head>, or prepend if missing
    const themedHtml = html.includes("</head>")
        ? html.replace("</head>", `<style>${overrideCSS}</style></head>`)
        : `<style>${overrideCSS}</style>` + html;

    return (
        <div
            style={{
                background: theme.palette.background.default,
                color: theme.palette.text.primary,
                fontFamily: theme.typography.fontFamily,
                minHeight: "100%",
            }}
            dangerouslySetInnerHTML={{ __html: themedHtml }}
        />
    );
}
