import { Modal, Input, Typography, Space, message } from "antd";
import { useState } from "react";
import { setTokenForDomain, getActiveDomain } from "../api/client";

interface Props {
  open: boolean;
  onClose: () => void;
  onSuccess?: () => void;
}

export function AuthPrompt({ open, onClose, onSuccess }: Props) {
  const [token, setToken] = useState("");
  return (
    <Modal
      open={open}
      title="Enter Access Token"
      onCancel={onClose}
      onOk={() => {
        if (!token.trim()) {
          message.error("Token required");
          return;
        }
        const domain = getActiveDomain();
        setTokenForDomain(domain, token.trim());
        message.success(`Token saved for domain ${domain}`);
        onSuccess?.();
        onClose();
      }}
      okText="Save"
    >
      <Space direction="vertical" style={{ width: "100%" }}>
        <Typography.Text>
          Enter your domain or admin token. It will be stored locally and used for all API calls.
        </Typography.Text>
        <Input.Password value={token} onChange={(e) => setToken(e.target.value)} placeholder="Token" />
      </Space>
    </Modal>
  );
}
