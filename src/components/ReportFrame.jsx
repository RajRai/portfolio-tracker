import React, { useEffect, useState } from "react";

export default function ReportFrame({ src }) {
    const [html, setHtml] = useState("");

    useEffect(() => {
        fetch(src)
            .then((r) => r.text())
            .then(setHtml)
            .catch(console.error);
    }, [src]);

    return (
        <div
            style={{
                padding: "16px",
                background: "white",
                fontFamily: "sans-serif",
            }}
            dangerouslySetInnerHTML={{ __html: html }}
        />
    );
}
