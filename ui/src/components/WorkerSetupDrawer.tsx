import { useMemo, useState } from "react";
import { Button, Drawer, Input, InputNumber, Radio, Space, Steps, Tag, Tooltip, Typography, Divider } from "antd";
import { CopyOutlined, CheckOutlined } from "@ant-design/icons";
import { useActiveDomain } from "../context/ActiveDomainContext";

const { Text, Paragraph, Title } = Typography;

type DeploymentMode = "docker" | "bare" | "windows" | "kubernetes";

const MODE_LABELS: Record<DeploymentMode, string> = {
  docker: "Docker Compose",
  bare: "Bare-metal / VM",
  windows: "Windows",
  kubernetes: "Kubernetes",
};

function CodeBlock({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = () => {
    if (!navigator.clipboard) return;
    navigator.clipboard.writeText(code).then(
      () => {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      },
      () => {},
    );
  };
  return (
    <div style={{ position: "relative", marginBottom: 8 }}>
      <pre
        style={{
          background: "var(--v2-bg-0, rgba(0,0,0,0.06))",
          border: "1px solid var(--v2-border, rgba(0,0,0,0.1))",
          borderRadius: 6,
          padding: "10px 12px",
          paddingRight: 44,
          fontSize: 12,
          overflowX: "auto",
          whiteSpace: "pre-wrap",
          wordBreak: "break-all",
          margin: 0,
          fontFamily: "var(--font-mono, monospace)",
          color: "var(--v2-text-1)",
          lineHeight: 1.7,
        }}
      >
        {code}
      </pre>
      <Tooltip title={copied ? "Copied!" : "Copy to clipboard"}>
        <Button
          size="small"
          aria-label="Copy command to clipboard"
          icon={copied ? <CheckOutlined /> : <CopyOutlined />}
          onClick={handleCopy}
          style={{ position: "absolute", top: 6, right: 6, opacity: 0.75 }}
        />
      </Tooltip>
    </div>
  );
}

function FieldLabel({ children, required }: { children: React.ReactNode; required?: boolean }) {
  return (
    <div style={{ fontSize: 12, fontWeight: 500, color: "var(--v2-text-2)", marginBottom: 4 }}>
      {children}
      {required && <span style={{ color: "var(--v2-error)", marginLeft: 2 }}>*</span>}
    </div>
  );
}

interface Props {
  open: boolean;
  onClose: () => void;
  redisUrl?: string;
}

export function WorkerSetupDrawer({ open, onClose, redisUrl: redisUrlProp }: Props) {
  const { domain: activeDomain } = useActiveDomain();
  const [mode, setMode] = useState<DeploymentMode>("docker");

  const defaultRedisUrl = redisUrlProp || "redis://<redis-host>:6379/0";

  // Live-configurable form fields
  const [domain, setDomain] = useState<string>("");
  const [apiToken, setApiToken] = useState<string>("");
  const [maxConcurrency, setMaxConcurrency] = useState<number>(12);
  const [tags, setTags] = useState<string>("batch, data");
  const [workerRedisUrl, setWorkerRedisUrl] = useState<string>(defaultRedisUrl);
  const [redisPassword, setRedisPassword] = useState<string>("");

  const effectiveDomain = domain || activeDomain || "prod";
  const effectiveToken = apiToken || "<your-domain-token>";
  const effectivePassword = redisPassword || "<your-redis-acl-password>";
  const tagsCleaned = tags
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean)
    .join(",");

  const generatedCommand = useMemo(() => {
    const envPrefix = [
      `DOMAIN=${effectiveDomain}`,
      `API_TOKEN=${effectiveToken}`,
      ...(redisPassword ? [`REDIS_PASSWORD=${redisPassword}`] : [`REDIS_PASSWORD=${effectivePassword}`]),
      `REDIS_URL=${workerRedisUrl}`,
      ...(maxConcurrency !== 12 ? [`MAX_CONCURRENCY=${maxConcurrency}`] : [`MAX_CONCURRENCY=${maxConcurrency}`]),
      ...(tagsCleaned ? [`WORKER_TAGS=${tagsCleaned}`] : []),
    ];

    if (mode === "docker") {
      return (
        envPrefix.map((e) => `${e} \\`).join("\n") +
        "\ndocker compose -f docker-compose.worker.yml up -d --build --scale worker=1"
      );
    }
    if (mode === "bare") {
      return (
        envPrefix.map((e) => `export ${e}`).join("\n") +
        "\npython -m worker"
      );
    }
    if (mode === "windows") {
      return (
        `# 1. Create runtime directory
New-Item -ItemType Directory -Force C:\\hydra-worker
New-Item -ItemType Directory -Force C:\\hydra-worker\\logs

# 2. Install worker
cd C:\\hydra-worker
uv venv .venv
uv pip install -e C:\\path\\to\\hydra

# 3. Write .env file
@"
DOMAIN=${effectiveDomain}
API_TOKEN=${effectiveToken}
REDIS_URL=${workerRedisUrl}
REDIS_PASSWORD=${effectivePassword}` +
        (tagsCleaned ? `\nWORKER_TAGS=${tagsCleaned}` : "") +
        `
MAX_CONCURRENCY=${maxConcurrency}
HYDRA_BOOTSTRAP_WORKING_DIR=C:\\hydra-worker
HYDRA_BOOTSTRAP_LOG_FILE=C:\\hydra-worker\\logs\\worker.log
PYTHONUNBUFFERED=1
"@ | Set-Content C:\\hydra-worker\\.env

# 4. Validate and install Task Scheduler watchdog
.venv\\Scripts\\python.exe -m worker bootstrap validate
.venv\\Scripts\\python.exe -m worker bootstrap install`
      );
    }
    // kubernetes — start-domain-workers.sh rotates its own token + Redis ACL via
    // ADMIN_TOKEN and takes `<domain> [scale]` as positional args; it does not
    // read API_TOKEN/REDIS_PASSWORD/REDIS_URL from the environment.
    return (
      `# Rotates a fresh domain token + Redis ACL and scales the K8s deployment.
ADMIN_TOKEN=<your-admin-token> \\
WORKER_BACKEND=k8s \\
K8S_NAMESPACE=hydra \\
K8S_DEPLOYMENT=hydra-worker \\
./scripts/start-domain-workers.sh ${effectiveDomain} 2`
    );
  }, [mode, effectiveDomain, effectiveToken, effectivePassword, redisPassword, workerRedisUrl, maxConcurrency, tagsCleaned, tags]);

  const modeHints: Record<DeploymentMode, string> = {
    docker: "Add --scale worker=N to run N workers in parallel. Workers auto-restart on crash (restart: unless-stopped).",
    bare: "Use a process supervisor (systemd, supervisord) to keep the worker alive. Set WORKER_ID to a unique value when running multiple workers on the same host.",
    windows: "The bootstrap installs a Task Scheduler watchdog that restarts the worker automatically. See docs/windows-worker-bootstrap.md for a full guide.",
    kubernetes: "This script rotates a fresh domain token + Redis ACL itself and writes them into a K8s Secret before scaling — the domain token / Redis fields above are not used for this path. Requires an admin token and kubectl access. Manifests are in deploy/k8s/worker-deployment.yaml.",
  };

  return (
    <Drawer
      title="Connect a Worker"
      placement="right"
      width={620}
      open={open}
      onClose={onClose}
    >
      <Space direction="vertical" size={20} style={{ width: "100%" }}>

        {/* Step 1: Deployment Method */}
        <div>
          <Title level={5} style={{ marginBottom: 8 }}>Step 1 — Deployment method</Title>
          <Radio.Group
            value={mode}
            onChange={(e) => setMode(e.target.value as DeploymentMode)}
            optionType="button"
            buttonStyle="solid"
          >
            {(["docker", "bare", "windows", "kubernetes"] as DeploymentMode[]).map((m) => (
              <Radio.Button key={m} value={m}>{MODE_LABELS[m]}</Radio.Button>
            ))}
          </Radio.Group>
        </div>

        <Divider style={{ margin: "4px 0" }} />

        {/* Step 2: Configuration */}
        <div>
          <Title level={5} style={{ marginBottom: 12 }}>Step 2 — Configure</Title>
          <Paragraph type="secondary" style={{ marginBottom: 12, fontSize: 13 }}>
            Fill in the values below. The startup command updates live as you type.
          </Paragraph>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px 16px" }}>
            <div>
              <FieldLabel required>Domain</FieldLabel>
              <Input
                placeholder={activeDomain || "prod"}
                value={domain}
                onChange={(e) => setDomain(e.target.value)}
              />
            </div>
            <div>
              <FieldLabel required>Domain Token</FieldLabel>
              <Input.Password
                placeholder="hydra_dom_…"
                value={apiToken}
                onChange={(e) => setApiToken(e.target.value)}
              />
            </div>
            <div>
              <FieldLabel>Max Concurrency</FieldLabel>
              <InputNumber
                min={1}
                max={256}
                value={maxConcurrency}
                onChange={(v) => setMaxConcurrency(v ?? 12)}
                style={{ width: "100%" }}
              />
            </div>
            <div>
              <FieldLabel>Worker Tags</FieldLabel>
              <Input
                placeholder="batch, data, postgres"
                value={tags}
                onChange={(e) => setTags(e.target.value)}
              />
            </div>
            <div style={{ gridColumn: "1 / -1" }}>
              <FieldLabel>Redis URL</FieldLabel>
              <Input
                value={workerRedisUrl}
                onChange={(e) => setWorkerRedisUrl(e.target.value)}
              />
            </div>
            <div style={{ gridColumn: "1 / -1" }}>
              <FieldLabel>
                Redis Password{" "}
                <Tag style={{ fontSize: 10, marginLeft: 4 }}>optional</Tag>
              </FieldLabel>
              <Input.Password
                placeholder="From 'Rotate Redis ACL' in Admin → Domains"
                value={redisPassword}
                onChange={(e) => setRedisPassword(e.target.value)}
              />
            </div>
          </div>
        </div>

        <Divider style={{ margin: "4px 0" }} />

        {/* Generated command */}
        <div>
          <Title level={5} style={{ marginBottom: 8 }}>Generated startup command</Title>
          <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 8 }}>
            Run this on the machine where you want to start the worker.
            {apiToken ? null : (
              <span style={{ color: "var(--v2-warning, #d97706)", marginLeft: 4 }}>
                Fill in the domain token above to get a ready-to-run command.
              </span>
            )}
          </Text>
          <CodeBlock code={generatedCommand} />
          <Text type="secondary" style={{ fontSize: 12 }}>
            {modeHints[mode]}
          </Text>
        </div>

        <Divider style={{ margin: "4px 0" }} />

        {/* Step 3: Verify */}
        <div>
          <Title level={5} style={{ marginBottom: 8 }}>Step 3 — Verify</Title>
          <Steps
            direction="vertical"
            size="small"
            items={[
              {
                title: "Worker comes online",
                description: "The worker should appear in the Workers table within ~5 seconds of starting.",
                status: "process",
              },
              {
                title: "Connectivity status is green",
                description: "Check the Connectivity column — it turns green once the heartbeat is received.",
                status: "wait",
              },
              {
                title: "Run a test job",
                description: "Use Operate → New Job to dispatch a quick shell job to confirm end-to-end execution.",
                status: "wait",
              },
            ]}
          />
        </div>

      </Space>
    </Drawer>
  );
}
