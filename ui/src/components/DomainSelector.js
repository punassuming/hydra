import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Select, Space, Typography } from "antd";
import { useEffect } from "react";
import { setDomain as storeDomain, getToken } from "../api/client";
import { useDomains } from "../hooks/useDomains";
export function DomainSelector({ onChange }) {
    const domainOptions = useDomains();
    const storedDomain = localStorage.getItem("hydra_domain") || domainOptions[0]?.domain || "prod";
    useEffect(() => {
        const existing = getToken();
        if (!existing)
            return;
    }, [storedDomain]);
    return (_jsxs(Space, { children: [_jsx(Typography.Text, { style: { color: "#cbd5f5" }, children: "Domain" }), _jsx(Select, { size: "small", value: storedDomain, options: domainOptions.map((o) => ({ label: o.label, value: o.domain })), onChange: (domain) => {
                    storeDomain(domain);
                    onChange?.(domain);
                }, style: { minWidth: 140 } })] }));
}
