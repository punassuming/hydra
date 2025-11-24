import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Card, Form, Input, Space, Table, Typography, Button, message, Modal, Input as AntInput, Select } from "antd";
import { fetchDomains, createDomain, updateDomain, DomainInfo } from "../api/admin";
import { setAuthToken, setDomain as storeDomain } from "../api/client";
import { createJob } from "../api/jobs";
import { useState } from "react";

export function AdminPage() {
  const queryClient = useQueryClient();
  const domainsQuery = useQuery({ queryKey: ["domains"], queryFn: fetchDomains, refetchInterval: 5000 });
  const [tokenModal, setTokenModal] = useState<{ open: boolean; token?: string; domain?: string }>({ open: false });
  const [switchModal, setSwitchModal] = useState<{ open: boolean; domain?: string; token?: string }>({ open: false });
  const [importText, setImportText] = useState("");
  const [importing, setImporting] = useState(false);
  const sampleOptions = [
    { key: "quick-shell", label: "Quick Shell", payload: {
      name: "quick-shell",
      user: "demo",
      affinity: { os: ["linux"], tags: [], allowed_users: [] },
      executor: { type: "shell", shell: "bash", script: "echo quick-ok" },
      retries: 0,
      timeout: 30,
      queue: "default",
      priority: 5,
      schedule: { mode: "immediate", enabled: true },
      completion: { exit_codes: [0], stdout_contains: ["quick-ok"], stdout_not_contains: [], stderr_contains: [], stderr_not_contains: [] },
    }},
    { key: "long-sleep", label: "Long Sleep", payload: {
      name: "long-sleep",
      user: "demo",
      affinity: { os: ["linux"], tags: [], allowed_users: [] },
      executor: { type: "shell", shell: "bash", script: "echo start; sleep 15; echo done" },
      retries: 0,
      timeout: 120,
      queue: "default",
      priority: 4,
      schedule: { mode: "immediate", enabled: true },
      completion: { exit_codes: [0], stdout_contains: ["done"], stdout_not_contains: ["error"], stderr_contains: [], stderr_not_contains: [] },
    }},
    { key: "python-env", label: "Python Env", payload: {
      name: "python-env",
      user: "demo",
      affinity: { os: ["linux"], tags: ["python"], allowed_users: [] },
      executor: {
        type: "python",
        interpreter: "python3",
        code: "import sys; import platform; print('pyversion:', sys.version.split()[0]); print('platform:', platform.system())",
        environment: { type: "system", python_version: "python3", requirements: [] },
      },
      retries: 0,
      timeout: 60,
      queue: "default",
      priority: 5,
      schedule: { mode: "immediate", enabled: true },
      completion: { exit_codes: [0], stdout_contains: ["pyversion:"], stdout_not_contains: [], stderr_contains: [], stderr_not_contains: [] },
    }},
    { key: "cron-ping", label: "Cron Ping", payload: {
      name: "cron-ping",
      user: "demo",
      affinity: { os: ["linux"], tags: [], allowed_users: [] },
      executor: { type: "shell", shell: "bash", script: "echo cron-run $(date +%s)" },
      retries: 0,
      timeout: 30,
      queue: "default",
      priority: 3,
      schedule: { mode: "cron", cron: "*/5 * * * *", enabled: true },
      completion: { exit_codes: [0], stdout_contains: ["cron-run"], stdout_not_contains: [], stderr_contains: [], stderr_not_contains: [] },
    }},
  ];
  const [selectedSample, setSelectedSample] = useState<string | undefined>(undefined);

  const createMut = useMutation({
    mutationFn: createDomain,
    onSuccess: () => {
      message.success("Domain created");
      queryClient.invalidateQueries({ queryKey: ["domains"] });
    },
    onError: (err: Error) => message.error(err.message),
  });

  const updateMut = useMutation({
    mutationFn: ({ domain, payload }: { domain: string; payload: Partial<DomainInfo> }) => updateDomain(domain, payload),
    onSuccess: () => {
      message.success("Domain updated");
      queryClient.invalidateQueries({ queryKey: ["domains"] });
    },
    onError: (err: Error) => message.error(err.message),
  });

  const columns = [
    { title: "Domain", dataIndex: "domain", key: "domain" },
    { title: "Display Name", dataIndex: "display_name", key: "display_name" },
    { title: "Description", dataIndex: "description", key: "description" },
    {
      title: "Actions",
      key: "actions",
      render: (_: unknown, record: DomainInfo) => (
        <Space>
          <Button
            size="small"
            onClick={() => updateMut.mutate({ domain: record.domain, payload: { display_name: record.display_name || record.domain } })}
          >
            Save Name
          </Button>
          <Button
            size="small"
            type="link"
            onClick={() => setSwitchModal({ open: true, domain: record.domain })}
          >
            Use Domain
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <Typography.Title level={3} style={{ marginBottom: 0 }}>
        Admin – Domains
      </Typography.Title>
      <Typography.Text type="secondary">
        Requires admin token. Manage domains and their metadata; update tokens and switch the UI session token when needed.
      </Typography.Text>
      <Card title="Create Domain">
        <Form
          layout="vertical"
          onFinish={(values) => {
            createMut.mutate(values as DomainInfo);
            if ((values as any).token) {
              setTokenModal({ open: true, token: (values as any).token, domain: (values as any).domain });
            }
          }}
        >
          <Form.Item name="domain" label="Domain" rules={[{ required: true }]}>
            <Input placeholder="dev" />
          </Form.Item>
          <Form.Item name="display_name" label="Display Name">
            <Input placeholder="Development" />
          </Form.Item>
          <Form.Item name="description" label="Description">
            <Input.TextArea rows={2} placeholder="Optional notes" />
          </Form.Item>
          <Form.Item name="token" label="Token (optional)">
            <Input placeholder="Leave blank to auto-generate" />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={createMut.isPending}>
            Create
          </Button>
        </Form>
      </Card>
      <Card title="Domains">
        <Table
          dataSource={(domainsQuery.data?.domains ?? []).map((d) => ({ ...d, key: d.domain }))}
          loading={domainsQuery.isLoading}
          columns={columns}
          pagination={false}
          size="small"
        />
      </Card>
      <Card title="Import Jobs">
        <Space direction="vertical" style={{ width: "100%" }}>
          <Typography.Text type="secondary">Paste a job JSON (single object or array) or use the sample set.</Typography.Text>
          <Space>
            <Select
              placeholder="Pick a sample job"
              style={{ minWidth: 200 }}
              value={selectedSample}
              onChange={(val) => {
                setSelectedSample(val);
                const sample = sampleOptions.find((s) => s.key === val);
                if (sample) {
                  setImportText(JSON.stringify(sample.payload, null, 2));
                }
              }}
              options={sampleOptions.map((s) => ({ label: s.label, value: s.key }))}
            />
            <Button
              onClick={() => {
                setImportText(JSON.stringify(sampleOptions.map((s) => s.payload), null, 2));
              }}
            >
              Load All Samples
            </Button>
          </Space>
          <AntInput.TextArea
            rows={6}
            placeholder="[{...job1...}, {...job2...}]"
            value={importText}
            onChange={(e) => setImportText(e.target.value)}
          />
          <Space>
            <Button
              onClick={async () => {
                const samples: any[] = [
                  {
                    name: "quick-shell",
                    user: "demo",
                    affinity: { os: ["linux"], tags: [], allowed_users: [] },
                    executor: { type: "shell", shell: "bash", script: "echo quick-ok" },
                    retries: 0,
                    timeout: 30,
                    queue: "default",
                    priority: 5,
                    schedule: { mode: "immediate", enabled: true },
                    completion: { exit_codes: [0], stdout_contains: ["quick-ok"], stdout_not_contains: [], stderr_contains: [], stderr_not_contains: [] },
                  },
                  {
                    name: "long-sleep",
                    user: "demo",
                    affinity: { os: ["linux"], tags: [], allowed_users: [] },
                    executor: { type: "shell", shell: "bash", script: "echo start; sleep 15; echo done" },
                    retries: 0,
                    timeout: 120,
                    queue: "default",
                    priority: 4,
                    schedule: { mode: "immediate", enabled: true },
                    completion: { exit_codes: [0], stdout_contains: ["done"], stdout_not_contains: ["error"], stderr_contains: [], stderr_not_contains: [] },
                  },
                  {
                    name: "python-env",
                    user: "demo",
                    affinity: { os: ["linux"], tags: ["python"], allowed_users: [] },
                    executor: {
                      type: "python",
                      interpreter: "python3",
                      code: "import sys; import platform; print('pyversion:', sys.version.split()[0]); print('platform:', platform.system())",
                      environment: { type: "system", python_version: "python3", requirements: [] },
                    },
                    retries: 0,
                    timeout: 60,
                    queue: "default",
                    priority: 5,
                    schedule: { mode: "immediate", enabled: true },
                    completion: { exit_codes: [0], stdout_contains: ["pyversion:"], stdout_not_contains: [], stderr_contains: [], stderr_not_contains: [] },
                  },
                  {
                    name: "cron-ping",
                    user: "demo",
                    affinity: { os: ["linux"], tags: [], allowed_users: [] },
                    executor: { type: "shell", shell: "bash", script: "echo cron-run $(date +%s)" },
                    retries: 0,
                    timeout: 30,
                    queue: "default",
                    priority: 3,
                    schedule: { mode: "cron", cron: "*/5 * * * *", enabled: true },
                    completion: { exit_codes: [0], stdout_contains: ["cron-run"], stdout_not_contains: [], stderr_contains: [], stderr_not_contains: [] },
                  },
                ];
                setImportText(JSON.stringify(samples, null, 2));
              }}
            >
              Load Sample Set
            </Button>
            <Button
              type="primary"
              loading={importing}
              onClick={async () => {
                let jobs: any[] = [];
                try {
                  const parsed = JSON.parse(importText);
                  jobs = Array.isArray(parsed) ? parsed : [parsed];
                } catch (err) {
                  message.error("Invalid JSON");
                  return;
                }
                setImporting(true);
                const results = await Promise.allSettled(jobs.map((j) => createJob(j as any)));
                const ok = results.filter((r) => r.status === "fulfilled").length;
                const fail = results.length - ok;
                if (ok) message.success(`Imported ${ok} job(s)`);
                if (fail) message.error(`${fail} job(s) failed`);
                queryClient.invalidateQueries({ queryKey: ["jobs"] });
                setImporting(false);
              }}
            >
              Import
            </Button>
          </Space>
        </Space>
      </Card>
      <Modal
        open={tokenModal.open}
        footer={null}
        onCancel={() => setTokenModal({ open: false })}
        title={`Domain Token – ${tokenModal.domain}`}
      >
        <Space direction="vertical" style={{ width: "100%" }}>
          <Typography.Text strong>Copy this token for workers and client access:</Typography.Text>
          <Typography.Paragraph code>{tokenModal.token ?? "(no token provided)"}</Typography.Paragraph>
        </Space>
      </Modal>
      <Modal
        open={switchModal.open}
        onCancel={() => setSwitchModal({ open: false })}
        onOk={() => {
          if (!switchModal.token || !switchModal.domain) {
            message.error("Enter a token");
            return;
          }
          setAuthToken(switchModal.token);
          storeDomain(switchModal.domain);
          message.success(`Switched to domain ${switchModal.domain}`);
          setSwitchModal({ open: false });
        }}
        title={`Activate domain ${switchModal.domain ?? ""}`}
      >
        <Space direction="vertical" style={{ width: "100%" }}>
          <Typography.Text strong>
            Enter the domain token (workers use this token too). The UI will start using this token immediately.
          </Typography.Text>
          <Input.Password
            value={switchModal.token}
            onChange={(e) => setSwitchModal((prev) => ({ ...prev, token: e.target.value }))}
            placeholder="Domain token"
          />
        </Space>
      </Modal>
    </Space>
  );
}
