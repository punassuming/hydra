import { Select, Space, Typography } from "antd";
import { useEffect } from "react";
import { setActiveDomain as storeDomain, getActiveDomain, setTokenForDomain, forgetToken } from "../api/client";
import { useDomains } from "../hooks/useDomains";
import { useState } from "react";

export function DomainSelector({ onChange }: { onChange?: (domain: string) => void }) {
  const domainOptions = useDomains();
  const [current, setCurrent] = useState<string>(getActiveDomain());

  useEffect(() => {
    setCurrent(getActiveDomain());
  }, []);

  return (
    <Space>
      <Typography.Text style={{ color: "#cbd5f5" }}>Domain</Typography.Text>
      <Select
        size="small"
        value={current}
        options={domainOptions.map((o) => ({ label: o.label, value: o.domain }))}
        onChange={(domain) => {
          storeDomain(domain);
          setCurrent(domain);
          onChange?.(domain);
        }}
        style={{ minWidth: 140 }}
      />
      <Typography.Link
        onClick={() => {
          forgetToken(current);
        }}
      >
        Forget Token
      </Typography.Link>
    </Space>
  );
}
