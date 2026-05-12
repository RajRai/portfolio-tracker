import React, { useEffect, useMemo, useRef, useState } from "react";
import { useTheme } from "@mui/material/styles";

export default function ReportFrame({ src }) {
    const theme = useTheme();
    const iframeRef = useRef(null);
    const [height, setHeight] = useState(800);
    const [loaded, setLoaded] = useState(false);

    const iframeUrl = useMemo(() => {
        if (!src) return "";

        const params = new URLSearchParams({
            embed: "1",
            mode: theme.palette.mode,
            bg: theme.palette.background.default,
            paper: theme.palette.background.paper,
            text: theme.palette.text.primary,
            divider: theme.palette.divider,
            hover: theme.palette.action.hover,
        });

        return `${src}?${params.toString()}`;
    }, [
        src,
        theme.palette.mode,
        theme.palette.background.default,
        theme.palette.background.paper,
        theme.palette.text.primary,
        theme.palette.divider,
        theme.palette.action.hover,
    ]);

    useEffect(() => {
        setLoaded(false);
        setHeight(800);
    }, [iframeUrl]);

    useEffect(() => {
        const iframe = iframeRef.current;
        if (!iframe || !iframeUrl) return undefined;

        let raf = 0;
        let timer = null;
        let stopped = false;

        const pad = 8;
        const intervalMs = 50;
        const maxMs = 2500;
        const stableCount = 8;

        let lastHeight = 0;
        let stable = 0;
        let elapsed = 0;

        const computeHeight = () => {
            const doc = iframe.contentDocument;
            if (!doc) return 0;
            const root = doc.documentElement;
            const body = doc.body;
            const rectHeight = root?.getBoundingClientRect?.().height || 0;

            return Math.max(
                root?.scrollHeight || 0,
                root?.offsetHeight || 0,
                root?.clientHeight || 0,
                body?.scrollHeight || 0,
                body?.offsetHeight || 0,
                rectHeight
            );
        };

        const stop = () => {
            if (stopped) return;
            stopped = true;
            if (timer) clearInterval(timer);
            timer = null;
        };

        const applyHeight = () => {
            cancelAnimationFrame(raf);
            raf = requestAnimationFrame(() => {
                const nextHeight = computeHeight();
                if (!nextHeight) return;

                if (Math.abs(nextHeight - lastHeight) <= 2) {
                    stable += 1;
                } else {
                    stable = 0;
                    lastHeight = nextHeight;
                    setHeight(nextHeight + pad);
                }

                elapsed += intervalMs;
                if (stable >= stableCount || elapsed >= maxMs) {
                    stop();
                }
            });
        };

        const onLoad = () => {
            setLoaded(true);
            lastHeight = 0;
            stable = 0;
            elapsed = 0;
            stopped = false;

            applyHeight();
            timer = setInterval(applyHeight, intervalMs);
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
        <>
            {!loaded && <div style={{ padding: 16 }}>Loading report...</div>}
            <iframe
                ref={iframeRef}
                title="QuantStats Report"
                src={iframeUrl}
                style={{
                    width: "100%",
                    height,
                    border: 0,
                    display: "block",
                    background: theme.palette.background.default,
                    borderRadius: 12,
                    visibility: loaded ? "visible" : "hidden",
                }}
            />
        </>
    );
}
