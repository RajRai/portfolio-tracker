import React, { useEffect, useRef, useState } from "react";
import { useTheme } from "@mui/material/styles";

export default function ReportFrame({ src }) {
    const theme = useTheme();
    const iframeRef = useRef(null);
    const [iframeUrl, setIframeUrl] = useState("");
    const [height, setHeight] = useState(800);

    // Keep CSS close to your original. Only change:
    // - Make SVG rule safe (only when viewBox exists)
    // - Make mobile stack deterministic (100% + clear) to avoid the “minor overlap”
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

.container::after {
  content: "";
  display: table;
  clear: both;
}

/* desktop: float columns */
#left {
  float: left !important;
  width: calc(100% - 400px) !important;
  box-sizing: border-box !important;
}

#right {
  float: right !important;
  width: 380px !important;
  box-sizing: border-box !important;
}

/* ==== SVG sizing (SAFE) ==== */
svg[viewBox] {
  width: 100% !important;
  height: auto !important;
  display: block !important;
  margin: 12px 0 !important;
}

/* mobile: stack (hard reset to prevent overlap) */
@media (max-width: 1050px) {
  #left, #right {
    float: none !important;
    width: 100% !important;
    clear: both !important;
    display: flow-root !important;   /* contains inner floats without scrollbars */
    position: static !important;
    box-sizing: border-box !important;
  }

  /* separation between stacked columns */
  #left { margin-bottom: 16px !important; }
  #right { margin-top: 0 !important; }

  /* belt-and-suspenders for any odd SVG positioning in mobile */
  svg { position: static !important; }

  /* contain/correct float-escape around plots without clearing everything */
  svg[viewBox] { clear: both !important; }
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

/* === Force QuantStats grid lines back on === */
table {
  border-collapse: collapse !important;
  border-spacing: 0 !important;
  border: 1px solid ${theme.palette.divider} !important;
}

table th, table td {
  border: 1px solid ${theme.palette.divider} !important;
}
`;

    useEffect(() => {
        if (!src) return;
        let cancelled = false;

        (async () => {
            const raw = await fetch(src).then((r) => r.text());
            if (cancelled) return;

            // 1) kill body onload="save()" without parsing
            let html = raw.replace(
                /<body([^>]*)\sonload=["'][^"']*["']([^>]*)>/i,
                "<body$1$2>"
            );

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

            // 4) load via blob URL so browser parses it natively
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

    useEffect(() => {
        const iframe = iframeRef.current;
        if (!iframe) return;

        let raf = 0;
        let timer = null;
        let stopped = false;

        const PAD = 8;
        const INTERVAL_MS = 50;
        const MAX_MS = 2500;
        const STABLE_COUNT = 8; // 8 * 50ms = 400ms stable

        let lastH = 0;
        let stable = 0;
        let elapsed = 0;

        const computeHeight = () => {
            const doc = iframe.contentDocument;
            if (!doc) return 0;
            const el = doc.documentElement;
            const body = doc.body;
            const rectH = el?.getBoundingClientRect?.().height || 0;

            return Math.max(
                el?.scrollHeight || 0,
                el?.offsetHeight || 0,
                el?.clientHeight || 0,
                body?.scrollHeight || 0,
                body?.offsetHeight || 0,
                rectH
            );
        };

        const applyHeight = () => {
            cancelAnimationFrame(raf);
            raf = requestAnimationFrame(() => {
                const h = computeHeight();
                if (!h) return;

                if (Math.abs(h - lastH) <= 2) {
                    stable += 1;
                } else {
                    stable = 0;
                    lastH = h;
                    setHeight(h + PAD);
                }

                // stop once stable, or after timeout
                elapsed += INTERVAL_MS;
                if (stable >= STABLE_COUNT || elapsed >= MAX_MS) stop();
            });
        };

        const stop = () => {
            if (stopped) return;
            stopped = true;
            if (timer) clearInterval(timer);
            timer = null;
        };

        const onLoad = () => {
            const doc = iframe.contentDocument;
            if (!doc) return;

            // reset polling state and start
            lastH = 0;
            stable = 0;
            elapsed = 0;
            stopped = false;

            // immediate measures + polling
            applyHeight();
            timer = setInterval(applyHeight, INTERVAL_MS);
        };

        iframe.addEventListener("load", onLoad);
        return () => {
            iframe.removeEventListener("load", onLoad);
            stop();
            cancelAnimationFrame(raf);
        };
    }, [iframeUrl]);

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
