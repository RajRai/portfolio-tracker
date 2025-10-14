import React, { useEffect, useState } from "react";
import { useTheme } from "@mui/material/styles";

export default function ReportFrame({ src }) {
    const [html, setHtml] = useState("");
    const theme = useTheme();

    useEffect(() => {
        fetch(src)
            .then((r) => r.text())
            .then((raw) => {
                let processed = raw;

                // --- Fix inline SVG width/height (handles pt, px, mixed) ---
                processed = processed.replace(
                    /<svg([^>]*?)width=["']([\d.]+)(pt|px)?["']([^>]*?)height=["']([\d.]+)(pt|px)?["']/gi,
                    (m, preW, wVal, wUnit, mid, hVal, hUnit) => {
                        let w = parseFloat(wVal);
                        let h = parseFloat(hVal);
                        if (wUnit === "pt") w *= 1.3333;
                        if (hUnit === "pt") h *= 1.3333;
                        if (w > 300) { w /= 2; h /= 2; }
                        return `<svg${preW}width="${Math.round(w)}px"${mid}height="${Math.round(h)}px"`;
                    }
                );

                // --- Also fix solo width="501pt" SVGs ---
                processed = processed.replace(
                    /width\s*=\s*["']\s*([\d.]+)\s*pt\s*["']/gi,
                    (_, w) => `width="${Math.round((parseFloat(w) * 1.3333) / 2)}px"`
                );

                // --- Fix left/right column widths ---
                processed = processed.replace(
                    /(<div[^>]+id=["']left["'][^>]+style=["'][^"']*?)width\s*:\s*\d+px\s*;?/gi,
                    '$1width: 90vw; margin: 0 auto;'
                );
                processed = processed.replace(
                    /(<div[^>]+id=["']right["'][^>]+style=["'][^"']*?)width\s*:\s*\d+px\s*;?/gi,
                    '$1width: 90vw; margin: 0 auto;'
                );

                // --- Strip outer <html> and <body> tags to prevent conflicts ---
                processed = processed.replace(/<\/?(html|body)[^>]*>/gi, "");

                setHtml(processed);
            })
            .catch(console.error);
    }, [src]);

    if (!html) return <div style={{ padding: 16 }}>Loading report...</div>;

    // ✅ All rules scoped under `.report-frame`
    const overrideCSS = `
      .report-frame {
        background-color: ${theme.palette.background.default} !important;
        color: ${theme.palette.text.primary} !important;
        font-family: ${theme.typography.fontFamily};
        overflow-x: hidden !important;
        width: 100%;
      }

      .report-frame h1,
      .report-frame h2,
      .report-frame h3,
      .report-frame h4,
      .report-frame h5,
      .report-frame h6 {
        color: ${theme.palette.text.primary} !important;
      }

      .report-frame a {
        color: ${theme.palette.primary.main} !important;
      }

      .report-frame table {
        border-collapse: collapse !important;
        width: 100% !important;
        background-color: transparent !important;
      }

      .report-frame th,
      .report-frame td {
        border: 1px solid ${theme.palette.divider} !important;
        color: ${theme.palette.text.primary} !important;
        background: transparent !important;
      }

      th {
        background-color: ${theme.palette.action.hover} !important;
        color: ${theme.palette.text.primary} !important;
        font-weight: 600 !important;
      }

      .report-frame tr:nth-of-type(even) td {
        background-color: ${theme.palette.action.selected} !important;
      }

      .report-frame #left,
      .report-frame #right {
        display: inline-block !important;
        vertical-align: top !important;
        margin: 0 auto !important;
        max-width: 90vw !important;
        float: none !important;
      }

      .report-frame #left img,
      .report-frame #left svg,
      .report-frame #right img,
      .report-frame #right svg {
        display: block !important;
        margin: 12px auto !important;
        height: auto !important;
        max-width: 100% !important;
      }

      /* ✅ Responsive stacking */
      @media (max-width: 900px) {
        .report-frame #left,
        .report-frame #right {
          display: block !important;
          width: 90vw !important;
          margin: 0 auto 24px auto !important;
          text-align: center !important;
        }
      }
    `;

    const themedHtml = html.includes("</head>")
        ? html.replace("</head>", `<style>${overrideCSS}</style></head>`)
        : `<style>${overrideCSS}</style>` + html;

    return (
        <div
            className="report-frame"
            style={{
                background: theme.palette.background.default,
                color: theme.palette.text.primary,
                fontFamily: theme.typography.fontFamily,
                width: "100%",
                overflowX: "hidden",
            }}
            dangerouslySetInnerHTML={{ __html: themedHtml }}
        />
    );
}
