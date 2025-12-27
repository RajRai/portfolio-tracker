import React, { useEffect, useMemo, useRef, useState } from "react";
import { useTheme } from "@mui/material/styles";

export default function ReportFrame({ src }) {
    const theme = useTheme();
    const iframeRef = useRef(null);
    const [iframeUrl, setIframeUrl] = useState("");
    const [height, setHeight] = useState(800);

    const injectedCSS = `
  :root { color-scheme: ${theme.palette.mode}; }

  html, body {
    margin: 0;
    padding: 0;
    background: ${theme.palette.background.default} !important;
    color: ${theme.palette.text.primary} !important;
  }

  body { padding: 16px; }

/* ==== Restore QuantStats 2-column layout ==== */
.container {
  max-width: 1200px;
  margin: 0 auto;
}

/* clearfix so floated columns don't escape the container */
.container::after {
  content: "";
  display: table;
  clear: both;
}

/* desktop: float columns */
#left {
  float: left !important;
  width: calc(100% - 400px) !important;  /* leaves room for right column */
}

#right {
  float: right !important;
  width: 380px !important;              /* tune this */
}

/* mobile: stack */
@media (max-width: 1050px) {
  #left, #right {
    float: none !important;
    width: auto !important;
  }
}

/* ==== SVG sizing (critical after removing width/height attrs) ==== */
svg {
  width: 100% !important;
  height: auto !important;
  display: block !important;
}

/* === Table theming using MUI palette === */
table {
  color: ${theme.palette.text.primary} !important;
  background: ${theme.palette.background.paper} !important;
  border-color: ${theme.palette.divider} !important;
}

table th, table td {
  color: ${theme.palette.text.primary} !important;
  border-color: ${theme.palette.divider} !important;
}

table thead th {
  background: ${theme.palette.action.hover} !important;
  font-weight: 600 !important;
}

`;

    useEffect(() => {
        if (!src) return;
        let cancelled = false;

        (async () => {
            const raw = await fetch(src).then((r) => r.text());
            if (cancelled) return;

            // 1) kill body onload="save()" without parsing
            let html = raw.replace(/<body([^>]*)\sonload=["'][^"']*["']([^>]*)>/i, "<body$1$2>");

            // 2) ensure <base target="_blank"> exists
            if (/<head[^>]*>/i.test(html) && !/<base\b/i.test(html)) {
                html = html.replace(/<head[^>]*>/i, (m) => `${m}\n<base target="_blank" />`);
            }

            // 3) inject our CSS late in <head> so it overrides QuantStats
            if (/<\/head>/i.test(html)) {
                html = html.replace(/<\/head>/i, `<style>${injectedCSS}</style></head>`);
            } else {
                html = `<style>${injectedCSS}</style>\n` + html;
            }

            // 4) load via blob URL so browser parses it natively (no DOMParser round-trip)
            const blob = new Blob([html], { type: "text/html;charset=utf-8" });
            const url = URL.createObjectURL(blob);
            setIframeUrl((prev) => {
                if (prev) URL.revokeObjectURL(prev);
                return url;
            });
        })().catch(console.error);

        return () => {
            cancelled = true;
            setIframeUrl((prev) => {
                if (prev) URL.revokeObjectURL(prev);
                return "";
            });
        };
    }, [src, injectedCSS]);

    // resize + patch SVG after iframe loads
    useEffect(() => {
        const iframe = iframeRef.current;
        if (!iframe) return;

        let ro = null;
        let raf = 0;

        const measure = () => {
            cancelAnimationFrame(raf);
            raf = requestAnimationFrame(() => {
                const doc = iframe.contentDocument;
                if (!doc) return;
                const h = Math.max(doc.documentElement?.scrollHeight || 0, doc.body?.scrollHeight || 0);
                if (h && Math.abs(h - height) > 4) setHeight(h);
            });
        };

        const onLoad = () => {
            const doc = iframe.contentDocument;
            if (!doc) return;

            // Patch SVG sizing *after* native parse
            doc.querySelectorAll("svg").forEach((svg) => {
                // safest: keep viewBox, remove fixed sizing
                svg.removeAttribute("width");
                svg.removeAttribute("height");
                if (!svg.getAttribute("preserveAspectRatio")) {
                    svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
                }
            });

            const measureSoon = () => requestAnimationFrame(measure);
            measureSoon();
            setTimeout(measure, 50);
            setTimeout(measure, 250);
            setTimeout(measure, 750);

            measure();

            try {
                ro = new ResizeObserver(measure);
                ro.observe(doc.documentElement);
                if (doc.body) ro.observe(doc.body);
            } catch {}
        };

        iframe.addEventListener("load", onLoad);
        return () => {
            iframe.removeEventListener("load", onLoad);
            if (ro) ro.disconnect();
            cancelAnimationFrame(raf);
        };
    }, [iframeUrl, height]);

    if (!iframeUrl) return <div style={{ padding: 16 }}>Loading report...</div>;

    return (
        <iframe
            ref={iframeRef}
            title="QuantStats Report"
            sandbox="allow-same-origin allow-popups allow-popups-to-escape-sandbox"
            src={iframeUrl}
            style={{
                width: "100%",
                height,
                border: 0,
                display: "block",
                background: theme.palette.background.default,
                borderRadius: 12,
            }}
        />
    );
}
