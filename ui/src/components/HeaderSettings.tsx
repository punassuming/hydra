import { useEffect, useMemo, useState } from "react";
import { Button, Divider, Drawer, Input, Select, Space, Tag, Typography, Tooltip, message } from "antd";
import { SettingOutlined } from "@ant-design/icons";
import { forgetToken, getAdminToken, hasTokenForDomain, setTokenForDomain, setTokenPreference } from "../api/client";
import { useDomains } from "../hooks/useDomains";
import { useActiveDomain } from "../context/ActiveDomainContext";

export function HeaderSettings() {
  const domainOptions = useDomains();
  const { domain: currentDomain, setDomain } = useActiveDomain();
  const [open, setOpen] = useState(false);
  const [tokenInput, setTokenInput] = useState("");
  const [adminTokenInput, setAdminTokenInput] = useState("");
  const [newDomainInput, setNewDomainInput] = useState("");
  const adminToken = getAdminToken();
  const availableDomains = domainOptions.map((o) => o.domain);
  const effectiveDomainOptions = useMemo(
    () => (domainOptions.length ? domainOptions : [{ domain: currentDomain, label: currentDomain }]),
    [domainOptions, currentDomain],
  );

  useEffect(() => {
    if (!availableDomains.length || availableDomains.includes(currentDomain)) {
      return;
    }
    const fallback = availableDomains.includes("prod") ? "prod" : availableDomains[0];
    setDomain(fallback);
  }, [availableDomains, currentDomain, setDomain]);

  const saveToken = () => {
    const token = tokenInput.trim();
    if (!token) {
      message.error("Token required");
      return;
    }
    setTokenForDomain(currentDomain, token);
    setTokenPreference("domain");
    message.success(`Token saved for domain ${currentDomain}`);
    setTokenInput("");
  };

  const applyDomain = (domain: string) => {
    const next = domain.trim();
    if (!next) return;
    setDomain(next);
    setNewDomainInput("");
  };

  const domainSelectOptions = Array.from(new Set([currentDomain, ...effectiveDomainOptions.map((o) => o.domain)])).map((domain) => {
    const hit = effectiveDomainOptions.find((o) => o.domain === domain);
    return { label: hit?.label || domain, value: domain };
  });

  return (
    <>
      <Tooltip title="Settings">
        <Button size="small" shape="circle" icon={<SettingOutlined />} aria-label="Open settings" onClick={() => setOpen(true)} />
      </Tooltip>
      <Drawer
        title="Workspace Settings"
        open={open}
        onClose={() => setOpen(false)}
        width={420}
        destroyOnHidden
      >
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <Typography.Text type="secondary">
            Worker auth key is a pair: <Typography.Text code>domain + token</Typography.Text>. Do not use a single{" "}
            <Typography.Text code>domain:token</Typography.Text> string.
          </Typography.Text>
          <Space direction="vertical" size={4}>
            <Typography.Text strong>Active domain</Typography.Text>
            <Select
              value={currentDomain}
              options={domainSelectOptions}
              onChange={applyDomain}
              showSearch
              dropdownRender={(menu) => (
                <>
                  {menu}
                  <Space style={{ padding: 8, width: "100%" }}>
                    <Input
                      size="small"
                      value={newDomainInput}
                      placeholder="Enter new domain"
                      onChange={(e) => setNewDomainInput(e.target.value)}
                      onPressEnter={() => applyDomain(newDomainInput)}
                    />
                    <Button size="small" onClick={() => applyDomain(newDomainInput)}>
                      Use
                    </Button>
                  </Space>
                </>
              )}
            />
            <Tag color={hasTokenForDomain(currentDomain) ? "green" : "volcano"}>
              {hasTokenForDomain(currentDomain) ? "Domain token saved" : "No domain token saved"}
            </Tag>
          </Space>

          <Space direction="vertical" size={8} style={{ width: "100%" }}>
            <Typography.Text strong>Token management</Typography.Text>
            <Input.Password
              value={tokenInput}
              placeholder={`Token for ${currentDomain}`}
              onChange={(e) => setTokenInput(e.target.value)}
            />
            <Space wrap>
              <Button type="primary" onClick={saveToken}>
                Save Token
              </Button>
              <Button
                onClick={() => {
                  forgetToken(currentDomain);
                  message.success(`Forgot token for ${currentDomain}`);
                }}
              >
                Forget Domain Token
              </Button>
            </Space>
            <Divider style={{ margin: "8px 0" }} />
            <Typography.Text strong>Admin token</Typography.Text>
            <Typography.Text type="secondary">
              Used for domain management. Kept separate from domain access tokens.
            </Typography.Text>
            <Input.Password
              value={adminTokenInput}
              onChange={(e) => setAdminTokenInput(e.target.value)}
              placeholder="Admin token"
            />
            <Space wrap>
              <Button
                onClick={() => {
                  const next = adminTokenInput.trim();
                  if (!next) {
                    message.error("Admin token required");
                    return;
                  }
                  setTokenForDomain("admin", next);
                  setAdminTokenInput("");
                  message.success("Admin token saved");
                }}
              >
                Save Admin Token
              </Button>
              <Button
                onClick={() => {
                  forgetToken("admin");
                  message.success("Forgot admin token");
                }}
              >
                Forget Admin Token
              </Button>
            </Space>
          </Space>

          {adminToken && (
            <>
              <Divider style={{ margin: "8px 0" }} />
              <Space direction="vertical" size={8} style={{ width: "100%" }}>
                <Typography.Text strong>Domain admin</Typography.Text>
                <Typography.Text type="secondary">
                  Use the Admin tab to create domains, rotate tokens, and manage credentials.
                </Typography.Text>
              </Space>
            </>
          )}

          <Divider style={{ margin: "8px 0" }} />

          <Space direction="vertical" size={8} style={{ width: "100%" }}>
            <Button
              danger
              onClick={() => {
                forgetToken();
                setOpen(false);
              }}
            >
              Sign Out (All Tokens)
            </Button>
          </Space>
        </Space>
      </Drawer>
    </>
  );
}
