import React, { useState } from "react";
import { Box, Typography, Dialog, DialogTitle, DialogContent } from "@mui/material";
import InfoOutlinedIcon from "@mui/icons-material/InfoOutlined";

const disclaimer = "This is not financial advice. Do your own research.";

export default function PortfolioAbout({ about, leftSlot = null }) {
    const [open, setOpen] = useState(false);
    const aboutText = about?.trim();
    const hasAbout = Boolean(aboutText);
    const hasLeftSlot = Boolean(leftSlot);

    if (!hasAbout && !hasLeftSlot) {
        return null;
    }

    return (
        <>
            <Box sx={{ px: { xs: 1.5, sm: 2 }, pt: 1, pb: 0.25 }}>
                <Box
                    sx={{
                        display: "grid",
                        gridTemplateColumns: {
                            xs: hasLeftSlot && hasAbout ? "minmax(0, 1fr) auto" : "1fr",
                            sm: hasAbout ? "minmax(0, 1fr) auto minmax(0, 1fr)" : "1fr",
                        },
                        gridTemplateAreas: {
                            xs: hasLeftSlot && hasAbout ? `"left center"` : hasLeftSlot ? `"left"` : `"center"`,
                            sm: hasAbout ? `"left center right"` : `"left"`,
                        },
                        alignItems: "center",
                        columnGap: 1,
                    }}
                >
                    <Box sx={{ minWidth: 0, justifySelf: "start", gridArea: "left", display: { xs: hasLeftSlot ? "block" : "none", sm: "block" } }}>
                        {leftSlot}
                    </Box>
                    {hasAbout && (
                        <Box sx={{ justifySelf: { xs: hasLeftSlot ? "end" : "center", sm: "center" }, gridArea: "center" }}>
                            <Box
                                component="button"
                                type="button"
                                onClick={() => setOpen(true)}
                                sx={{
                                    display: "inline-flex",
                                    alignItems: "center",
                                    gap: 0.5,
                                    p: 0,
                                    border: 0,
                                    borderBottom: (theme) => `1px dashed ${theme.palette.action.disabled}`,
                                    background: "transparent",
                                    color: "text.secondary",
                                    font: "inherit",
                                    fontSize: "0.72rem",
                                    opacity: 0.72,
                                    cursor: "pointer",
                                }}
                            >
                                About this portfolio
                                <InfoOutlinedIcon sx={{ fontSize: 14 }} />
                            </Box>
                        </Box>
                    )}
                    {hasAbout && <Box sx={{ display: { xs: "none", sm: "block" }, gridArea: "right" }} />}
                </Box>
            </Box>

            {hasAbout && (
                <Dialog open={open} onClose={() => setOpen(false)} fullWidth maxWidth="sm">
                    <DialogTitle>About this portfolio</DialogTitle>
                    <DialogContent dividers>
                        <Typography variant="body2" sx={{ whiteSpace: "pre-wrap" }}>
                            {aboutText}
                        </Typography>
                        <Typography variant="caption" sx={{ display: "block", mt: 2.5, color: "text.secondary" }}>
                            {disclaimer}
                        </Typography>
                    </DialogContent>
                </Dialog>
            )}
        </>
    );
}
