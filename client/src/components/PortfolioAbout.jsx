import React, { useState } from "react";
import { Button, Typography, Dialog, DialogTitle, DialogContent } from "@mui/material";
import InfoOutlinedIcon from "@mui/icons-material/InfoOutlined";

const disclaimer = "This is not financial advice. Do your own research.";

export default function PortfolioAbout({ about }) {
    const [open, setOpen] = useState(false);
    const aboutText = about?.trim();
    if (!aboutText) return null;

    return (
        <>
            <Button
                size="small"
                variant="text"
                onClick={() => setOpen(true)}
                endIcon={<InfoOutlinedIcon sx={{ fontSize: 16 }} />}
                sx={{
                    minWidth: 0,
                    px: 0.75,
                    py: 0.25,
                    color: "text.secondary",
                    textTransform: "none",
                    fontSize: "0.78rem",
                    fontWeight: 500,
                    whiteSpace: "nowrap",
                }}
            >
                About
            </Button>

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
        </>
    );
}
