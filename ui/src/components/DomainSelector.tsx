import { Select, Space, Typography, Button, Modal, Input } from "antd";
import { useEffect, useState } from "react";
import {
  setActiveDomain as storeDomain,
  getActiveDomain,
  setTokenForDomain,
  forgetToken,
  getAdminToken,
} from "../api/client";
import { useDomains } from "../hooks/useDomains";

export function DomainSelector({ onChange }: { onChange?: (domain: string) => void }) {
  const domainOptions = useDomains();
  const [current, setCurrent] = useState<string>(getActiveDomain());
  const [switchModal, setSwitchModal] = useState<{ open: boolean; domain?: string; token?: string }>({ open: false });
  const adminToken = getAdminToken();

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
      <Button size="small" onClick={() => setSwitchModal({ open: true, domain: current })}>
        Switch Token
      </Button>
      {adminToken && (
        <Button
          size="small"
          onClick={() => {
            setTokenForDomain(current, adminToken);
            storeDomain(current);
            setCurrent(current);
            onChange?.(current);
          }}
        >
          Use Admin
        </Button>
      )}
      <Typography.Link
        onClick={() => {
          forgetToken(current);
        }}
      >
        Forget Token
      </Typography.Link>
      <Modal
        open={switchModal.open}
        title={`Set token for ${switchModal.domain}`}
        onCancel={() => setSwitchModal({ open: false })}
        onOk={() => {
          if (switchModal.domain && switchModal.token) {
            setTokenForDomain(switchModal.domain, switchModal.token);
            storeDomain(switchModal.domain);
            setCurrent(switchModal.domain);
            onChange?.(switchModal.domain);
            setSwitchModal({ open: false });
          }
        }}
      >
        <Input
          placeholder="Token"
          value={switchModal.token}
          onChange={(e) => setSwitchModal((prev) => ({ ...prev, token: e.target.value }))}
        />
      </Modal>
    </Space>
  );
}
