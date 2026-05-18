import React from "react";
import {
    Button,
    FormControl,
    InputLabel,
    MenuItem,
    Select,
    Stack,
} from "@mui/material";

export const splitTickers = (value) =>
    String(value || "")
        .toUpperCase()
        .split(/[\s,;]+/)
        .map((ticker) => ticker.trim().replace(/^\$/, ""))
        .filter((ticker) => /^[A-Z0-9][A-Z0-9.-]*$/.test(ticker));

export const normalizeTicker = (value) => splitTickers(value)[0] || "";

export const formatPercent = (value) =>
    value == null ? "" : `${(Number(value) * 100).toFixed(2)}%`;

export async function postJson(url, body) {
    const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
        throw new Error(payload.error || "Request failed");
    }
    return payload;
}

export function SourcePicker({
    accounts,
    accountId,
    setAccountId,
    onLoad,
    loading,
    label = "Portfolio",
    buttonLabel = "Load Portfolio",
}) {
    return (
        <Stack direction={{ xs: "column", md: "row" }} spacing={1.25} alignItems={{ md: "center" }}>
            <FormControl size="small" sx={{ minWidth: 260 }} disabled={!accounts.length}>
                <InputLabel>{label}</InputLabel>
                <Select
                    value={accountId}
                    label={label}
                    onChange={(event) => setAccountId(event.target.value)}
                >
                    {accounts.map((account) => (
                        <MenuItem key={account.id} value={account.id}>
                            {account.name}
                        </MenuItem>
                    ))}
                </Select>
            </FormControl>

            <Button
                variant="outlined"
                onClick={onLoad}
                disabled={loading || !accountId}
            >
                {buttonLabel}
            </Button>
        </Stack>
    );
}
