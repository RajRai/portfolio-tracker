import React, { useState } from "react";
import { Box, Typography, Dialog, DialogTitle, DialogContent } from "@mui/material";
import InfoOutlinedIcon from "@mui/icons-material/InfoOutlined";

const fallbackText = "No additional portfolio notes are configured for this portfolio yet.";
const disclaimer = "This is not financial advice. Do your own research.";

export default function PortfolioAbout({ about }) {
    const [open, setOpen] = useState(false);

    return (
        <>
            <Box sx={{ px: { xs: 1.5, sm: 2 }, pt: 1, pb: 0.25, display: "flex", justifyContent: "center" }}>
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

            <Dialog open={open} onClose={() => setOpen(false)} fullWidth maxWidth="sm">
                <DialogTitle>About this portfolio</DialogTitle>
                <DialogContent dividers>
                    <Typography variant="body2" sx={{ whiteSpace: "pre-wrap" }}>
                        {about?.trim() || fallbackText}
                    </Typography>
                    <Typography variant="caption" sx={{ display: "block", mt: 2.5, color: "text.secondary" }}>
                        {disclaimer}
                    </Typography>
                </DialogContent>
            </Dialog>
        </>
    );
}
