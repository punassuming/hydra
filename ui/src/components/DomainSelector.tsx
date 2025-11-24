import { Select, Space, Typography } from "antd";
import { useEffect } from "react";
import { setDomain as storeDomain, setAuthToken, getToken } from "../api/client";
import { useDomains } from "../hooks/useDomains";

export function DomainSelector({ onChange }: { onChange?: (domain: string) => void }) {
  const domainOptions = useDomains();
  const storedDomain = localStorage.getItem("hydra_domain") || domainOptions[0]?.domain || "prod";

  useEffect(() => {
    const existing = getToken();
    if (!existing) return;
  }, [storedDomain]);

  return (
    <Space>
      <Typography.Text style={{ color: "#cbd5f5" }}>Domain</Typography.Text>
      <Select
        size="small"
        value={storedDomain}
        options={domainOptions.map((o) => ({ label: o.label, value: o.domain }))}
        onChange={(domain) => {
          storeDomain(domain);
          onChange?.(domain);
        }}
        style={{ minWidth: 140 }}
      />
    </Space>
  );
}
