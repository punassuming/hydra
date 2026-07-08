import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Card, Form, Input, Space, Table, Typography, Button, message, Modal, Input as AntInput, Select, Divider, Tooltip } from "antd";
import { CopyOutlined, CheckOutlined } from "@ant-design/icons";
import {
  fetchDomains,
  createDomain,
  updateDomain,
  DomainInfo,
  rotateDomainToken,
  rotateDomainWorkerRedisAcl,
  fetchTemplates,
  importTemplate,
  deleteDomain,
  WorkerRedisAclInfo,
  fetchCredentials,
  createCredential,
  updateCredential,
  deleteCredential,
  CredentialRef,
  CredentialPayload,
} from "../api/admin";
import {
  fetchMyCredentials,
  createMyCredential,
  updateMyCredential,
  deleteMyCredential,
  fetchMyDomainSettings,
  updateMyDomainSettings,
  rotateMyDomainToken,
  rotateMyDomainWorkerRedisAcl,
} from "../api/domain";
import { setTokenForDomain, getEffectiveToken, withTempToken, hasTokenForDomain, getAdminToken } from "../api/client";
import { createJob } from "../api/jobs";
import { useEffect, useState } from "react";
import { useActiveDomain } from "../context/ActiveDomainContext";

function CopyableCode({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = () => {
    navigator.clipboard?.writeText(code).then(
      () => { setCopied(true); setTimeout(() => setCopied(false), 2000); },
      () => {},
    );
  };
  return (
    <div style={{ position: "relative" }}>
      <pre
        style={{
          background: "var(--v2-bg-0, #0a0e14)",
          border: "1px solid var(--v2-border, rgba(0,0,0,0.15))",
          borderRadius: 6,
          padding: "10px 44px 10px 12px",
          fontSize: 12,
          lineHeight: 1.7,
          overflowX: "auto",
          whiteSpace: "pre-wrap",
          wordBreak: "break-all",
          margin: 0,
          fontFamily: "var(--font-mono, monospace)",
          color: "var(--v2-text-1, #e2e8f0)",
        }}
      >
        {code}
      </pre>
      <Tooltip title={copied ? "Copied!" : "Copy"}>
        <Button
          size="small"
          icon={copied ? <CheckOutlined /> : <CopyOutlined />}
          onClick={handleCopy}
          style={{ position: "absolute", top: 6, right: 6, opacity: 0.75 }}
        />
      </Tooltip>
    </div>
  );
}

function normalizeCredentialPayload(values: any): CredentialPayload {
  const payload: CredentialPayload = {
    name: values.name,
    credential_type: values.credential_type,
    dialect: values.dialect || undefined,
    connection_uri: values.connection_uri || undefined,
    username: values.username || undefined,
    password: values.password || undefined,
    host: values.host || undefined,
    port: values.port ? Number(values.port) : undefined,
    database: values.database || undefined,
  };
  if (values.extra_json) {
    payload.extra = JSON.parse(values.extra_json);
  }
  return payload;
}

function CredentialTypeFields() {
  return (
    <Form.Item noStyle shouldUpdate={(prev, cur) => prev.credential_type !== cur.credential_type}>
      {({ getFieldValue }) => {
        const type = getFieldValue("credential_type") || "database";
        if (type === "database") {
          return (
            <>
              <Form.Item name="dialect" label="Dialect">
                <Select allowClear placeholder="Select dialect" options={[
                  { label: "PostgreSQL", value: "postgres" },
                  { label: "MySQL", value: "mysql" },
                  { label: "MSSQL", value: "mssql" },
                  { label: "Oracle", value: "oracle" },
                  { label: "MongoDB", value: "mongodb" },
                ]} />
              </Form.Item>
              <Form.Item name="connection_uri" label="Connection URI">
                <Input.Password placeholder="postgresql://user:pass@host/db" />
              </Form.Item>
              <Form.Item name="username" label="Username">
                <Input placeholder="db_user" />
              </Form.Item>
              <Form.Item name="password" label="Password">
                <Input.Password placeholder="Password" />
              </Form.Item>
              <Form.Item name="host" label="Host">
                <Input placeholder="db.example.com" />
              </Form.Item>
              <Form.Item name="port" label="Port">
                <Input type="number" placeholder="5432" />
              </Form.Item>
              <Form.Item name="database" label="Database">
                <Input placeholder="mydb" />
              </Form.Item>
            </>
          );
        }
        if (type === "api_key") {
          return (
            <>
              <Form.Item name="username" label="Key Name (optional)">
                <Input placeholder="Authorization" />
              </Form.Item>
              <Form.Item name="password" label="API Key / Token" rules={[{ required: true }]}>
                <Input.Password placeholder="sk-..." />
              </Form.Item>
              <Form.Item name="extra_json" label="Extra JSON (optional)">
                <AntInput.TextArea rows={3} placeholder='{"base_url":"https://api.example.com"}' />
              </Form.Item>
            </>
          );
        }
        return (
          <>
            <Form.Item name="username" label="Username (optional)">
              <Input placeholder="service_user" />
            </Form.Item>
            <Form.Item name="password" label="Secret" rules={[{ required: true }]}>
              <Input.Password placeholder="Secret value" />
            </Form.Item>
            <Form.Item name="extra_json" label="Extra JSON (optional)">
              <AntInput.TextArea rows={3} placeholder='{"region":"us-east-1"}' />
            </Form.Item>
          </>
        );
      }}
    </Form.Item>
  );
}

export function AdminPage() {
  const queryClient = useQueryClient();
  const adminToken = getAdminToken();
  const isAdmin = Boolean(adminToken);
  const domainsQuery = useQuery({
    queryKey: ["domains"],
    queryFn: fetchDomains,
    refetchInterval: 5000,
    enabled: isAdmin,
  });
  const [tokenModal, setTokenModal] = useState<{ open: boolean; token?: string; domain?: string }>({ open: false });
  const [redisAclModal, setRedisAclModal] = useState<{ open: boolean; domain?: string; acl?: WorkerRedisAclInfo }>({ open: false });
  const [switchModal, setSwitchModal] = useState<{ open: boolean; domain?: string; token?: string }>({ open: false });
  const [importText, setImportText] = useState("");
  const [importing, setImporting] = useState(false);
  const [importToken, setImportToken] = useState("");
  const { domain: activeDomain, setDomain } = useActiveDomain();
  const [importDomain, setImportDomain] = useState<string>(activeDomain);
  useEffect(() => setImportDomain(activeDomain), [activeDomain]);
  const [createCredForm] = Form.useForm();
  const [updateCredForm] = Form.useForm();
  const [domainSettingsForm] = Form.useForm();
  const rotateMut = useMutation({
    mutationFn: (domain: string) => rotateDomainToken(domain),
    onSuccess: (data) => {
      message.success("Token rotated");
      setTokenModal({ open: true, token: data.token, domain: data.domain });
      queryClient.invalidateQueries({ queryKey: ["domains"] });
    },
    onError: (err: Error) => message.error(err.message),
  });
  const rotateWorkerAclMut = useMutation({
    mutationFn: (domain: string) => rotateDomainWorkerRedisAcl(domain),
    onSuccess: (data) => {
      setRedisAclModal({ open: true, domain: data.domain, acl: data.worker_redis_acl });
      message.success(`Worker Redis ACL rotated for ${data.domain}`);
      queryClient.invalidateQueries({ queryKey: ["domains"] });
    },
    onError: (err: Error) => message.error(err.message),
  });
  const deleteMut = useMutation({
    mutationFn: (domain: string) => deleteDomain(domain),
    onSuccess: () => {
      message.success("Domain deleted");
      queryClient.invalidateQueries({ queryKey: ["domains"] });
    },
    onError: (err: Error) => message.error(err.message),
  });
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
  const templatesQuery = useQuery({ queryKey: ["templates"], queryFn: fetchTemplates, staleTime: 10000, enabled: isAdmin });

  const domainSettingsQuery = useQuery({
    queryKey: ["domain-settings", activeDomain],
    queryFn: fetchMyDomainSettings,
    refetchInterval: 10000,
  });
  useEffect(() => {
    if (domainSettingsQuery.data) {
      domainSettingsForm.setFieldsValue({
        display_name: domainSettingsQuery.data.display_name || activeDomain,
        description: domainSettingsQuery.data.description || "",
      });
    }
  }, [domainSettingsQuery.data, domainSettingsForm, activeDomain]);

  // --- Credential management state ---
  const [credDomain, setCredDomain] = useState<string>(activeDomain);
  useEffect(() => setCredDomain(activeDomain), [activeDomain]);
  const credentialsQuery = useQuery({
    queryKey: ["credentials", isAdmin ? credDomain : activeDomain, isAdmin ? "admin" : "domain"],
    queryFn: () => (isAdmin ? fetchCredentials(credDomain) : fetchMyCredentials()),
    refetchInterval: 10000,
  });
  const [credFormVisible, setCredFormVisible] = useState(false);
  const [editingCred, setEditingCred] = useState<CredentialRef | null>(null);

  const createCredMut = useMutation({
    mutationFn: (payload: CredentialPayload) => (isAdmin ? createCredential(payload, credDomain) : createMyCredential(payload)),
    onSuccess: () => {
      message.success("Credential created");
      queryClient.invalidateQueries({ queryKey: ["credentials"] });
      setCredFormVisible(false);
      createCredForm.resetFields();
    },
    onError: (err: Error) => message.error(err.message),
  });
  const updateCredMut = useMutation({
    mutationFn: ({ name, payload }: { name: string; payload: CredentialPayload }) =>
      (isAdmin ? updateCredential(name, payload, credDomain) : updateMyCredential(name, payload)),
    onSuccess: () => {
      message.success("Credential updated");
      queryClient.invalidateQueries({ queryKey: ["credentials"] });
      setEditingCred(null);
      updateCredForm.resetFields();
    },
    onError: (err: Error) => message.error(err.message),
  });
  const deleteCredMut = useMutation({
    mutationFn: (name: string) => (isAdmin ? deleteCredential(name, credDomain) : deleteMyCredential(name)),
    onSuccess: () => {
      message.success("Credential deleted");
      queryClient.invalidateQueries({ queryKey: ["credentials"] });
    },
    onError: (err: Error) => message.error(err.message),
  });

  const updateMyDomainMut = useMutation({
    mutationFn: (payload: { display_name: string; description?: string }) => updateMyDomainSettings(payload),
    onSuccess: () => {
      message.success("Domain settings updated");
      queryClient.invalidateQueries({ queryKey: ["domain-settings", activeDomain] });
      queryClient.invalidateQueries({ queryKey: ["domains"] });
    },
    onError: (err: Error) => message.error(err.message),
  });
  const rotateMyTokenMut = useMutation({
    mutationFn: () => rotateMyDomainToken(),
    onSuccess: (data) => {
      message.success("Domain token rotated");
      setTokenModal({ open: true, token: data.token, domain: data.domain });
    },
    onError: (err: Error) => message.error(err.message),
  });
  const rotateMyAclMut = useMutation({
    mutationFn: () => rotateMyDomainWorkerRedisAcl(),
    onSuccess: (data) => {
      setRedisAclModal({ open: true, domain: data.domain, acl: data.worker_redis_acl });
      message.success("Worker Redis ACL rotated");
    },
    onError: (err: Error) => message.error(err.message),
  });

  const createMut = useMutation({
    mutationFn: createDomain,
    onSuccess: (data) => {
      if (data?.token) {
        message.success("Domain created. Token shown below.");
        setTokenModal({ open: true, token: data.token, domain: data.domain });
      } else {
        message.success("Domain created");
      }
      if ((data as any)?.worker_redis_acl) {
        setRedisAclModal({ open: true, domain: data.domain, acl: (data as any).worker_redis_acl });
      }
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
    { title: "Jobs", dataIndex: "jobs_count", key: "jobs_count" },
    { title: "Runs", dataIndex: "runs_count", key: "runs_count" },
    { title: "Workers", dataIndex: "workers_count", key: "workers_count" },
    {
      title: "Actions",
      key: "actions",
      render: (_: unknown, record: DomainInfo) => (
        <Space>
          <Button
            size="small"
            onClick={() => updateMut.mutate({ domain: record.domain, payload: { display_name: record.display_name || record.domain } })}
          >
            Save Display Name
          </Button>
          <Button size="small" onClick={() => rotateMut.mutate(record.domain)}>
            Rotate Token
          </Button>
          <Button size="small" onClick={() => rotateWorkerAclMut.mutate(record.domain)} loading={rotateWorkerAclMut.isPending}>
            Rotate Worker Redis ACL
          </Button>
          <Button
            size="small"
            type="link"
            onClick={() => {
              if (adminToken) {
                setTokenForDomain(record.domain, adminToken);
                setDomain(record.domain);
                message.success(`Using admin token for domain ${record.domain}`);
              } else if (hasTokenForDomain(record.domain)) {
                setDomain(record.domain);
                message.success(`Switched to domain ${record.domain}`);
              } else {
                setSwitchModal({ open: true, domain: record.domain });
              }
            }}
          >
            Use Domain
          </Button>
          <Button size="small" danger onClick={() => deleteMut.mutate(record.domain)}>
            Delete
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <Typography.Title level={3} style={{ marginBottom: 0 }}>
        {isAdmin ? "Admin – Domains" : `Domain Settings – ${activeDomain}`}
      </Typography.Title>
      <Typography.Text type="secondary">
        {isAdmin
          ? "Manage domains and metadata, rotate auth material, and maintain credentials."
          : "Manage your active domain settings and credentials with your domain token."}
      </Typography.Text>
      <Card title="Worker Auth & Setup">
        <Space direction="vertical" style={{ width: "100%" }} size={8}>
          <Typography.Text>
            Worker authentication is a pair: <Typography.Text code>domain + token</Typography.Text>. Do not combine them into a single string.
          </Typography.Text>
          <Typography.Text type="secondary">
            1) Create or rotate a domain token below. &nbsp;2) Start worker with that domain + token.
            Optional: rotate the worker Redis ACL and pass <Typography.Text code>REDIS_PASSWORD</Typography.Text> for extra isolation.
          </Typography.Text>
          <CopyableCode code={`DOMAIN=${activeDomain} API_TOKEN=<domain_token> \\
REDIS_URL=redis://<redis-host>:6379/0 \\
REDIS_PASSWORD=<worker_redis_acl_password> \\
docker compose -f docker-compose.worker.yml up -d --build`} />
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            After rotating a token below, the modal will show a ready-to-run command with the actual credential values filled in.
          </Typography.Text>
        </Space>
      </Card>
      <Card title={`Current Domain Settings (${activeDomain})`}>
        <Form
          form={domainSettingsForm}
          layout="vertical"
          onFinish={(values) => {
            updateMyDomainMut.mutate({
              display_name: values.display_name || activeDomain,
              description: values.description || "",
            });
          }}
        >
          <Form.Item name="display_name" label="Display Name" rules={[{ required: true }]}>
            <Input placeholder={activeDomain} />
          </Form.Item>
          <Form.Item name="description" label="Description">
            <Input.TextArea rows={2} placeholder="Optional notes" />
          </Form.Item>
          <Space>
            <Button type="primary" htmlType="submit" loading={updateMyDomainMut.isPending}>
              Save Domain Settings
            </Button>
            <Button onClick={() => rotateMyTokenMut.mutate()} loading={rotateMyTokenMut.isPending}>
              Rotate My Domain Token
            </Button>
            <Button onClick={() => rotateMyAclMut.mutate()} loading={rotateMyAclMut.isPending}>
              Rotate My Redis ACL
            </Button>
          </Space>
        </Form>
      </Card>
      {isAdmin && (
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
      )}
      {isAdmin && (
      <Card title="Domains">
        <Table
          dataSource={(domainsQuery.data?.domains ?? []).map((d) => ({ ...d, key: d.domain }))}
          loading={domainsQuery.isLoading}
          columns={columns}
          pagination={false}
          size="small"
        />
      </Card>
      )}
      <Card title={`Credentials (domain: ${isAdmin ? credDomain : activeDomain})`}>
        <Space direction="vertical" style={{ width: "100%" }}>
          <Typography.Text type="secondary">
            Manage encrypted credentials for this domain. Secrets are write-only — you can create or update them, but the stored values are never displayed.
          </Typography.Text>
          <Typography.Text type="secondary">
            Use secrets in jobs by setting <Typography.Text code>executor.credential_ref</Typography.Text> to the credential name
            (for SQL jobs, this is resolved server-side to a connection URI at dispatch time).
          </Typography.Text>
          {isAdmin && (
            <Select
              style={{ minWidth: 200 }}
              placeholder="Select domain for credentials"
              options={domainsQuery.data?.domains?.map((d) => ({ label: d.domain, value: d.domain })) ?? []}
              value={credDomain}
              onChange={(val) => setCredDomain(val)}
            />
          )}
          <Table
            dataSource={(credentialsQuery.data?.credentials ?? []).map((c) => ({ ...c, key: c.name }))}
            loading={credentialsQuery.isLoading}
            columns={[
              { title: "Name", dataIndex: "name", key: "name" },
              { title: "Type", dataIndex: "credential_type", key: "credential_type" },
              { title: "Dialect", dataIndex: "dialect", key: "dialect" },
              { title: "Updated", dataIndex: "updated_at", key: "updated_at" },
              {
                title: "Actions",
                key: "actions",
                render: (_: unknown, record: CredentialRef) => (
                  <Space>
                    <Button
                      size="small"
                      onClick={() => {
                        setEditingCred(record);
                        updateCredForm.setFieldsValue({
                          credential_type: record.credential_type || "database",
                          dialect: record.dialect || undefined,
                        });
                      }}
                    >
                      Update Secret
                    </Button>
                    <Button size="small" danger onClick={() => deleteCredMut.mutate(record.name)}>
                      Delete
                    </Button>
                  </Space>
                ),
              },
            ]}
            pagination={false}
            size="small"
          />
          <Button type="primary" onClick={() => setCredFormVisible(true)}>
            Add Credential
          </Button>
        </Space>
      </Card>
      <Modal
        open={credFormVisible}
        title="Add Credential"
        onCancel={() => {
          setCredFormVisible(false);
          createCredForm.resetFields();
        }}
        footer={null}
      >
        <Form
          form={createCredForm}
          layout="vertical"
          initialValues={{ credential_type: "database" }}
          onFinish={(values) => {
            try {
              createCredMut.mutate(normalizeCredentialPayload(values));
            } catch (err) {
              message.error("Invalid extra JSON");
            }
          }}
        >
          <Form.Item name="name" label="Name" rules={[{ required: true }]}>
            <Input placeholder="prod-db" />
          </Form.Item>
          <Form.Item name="credential_type" label="Type" initialValue="database">
            <Select options={[
              { label: "Database", value: "database" },
              { label: "API Key", value: "api_key" },
              { label: "Generic", value: "generic" },
            ]} />
          </Form.Item>
          <CredentialTypeFields />
          <Button type="primary" htmlType="submit" loading={createCredMut.isPending}>
            Create
          </Button>
        </Form>
      </Modal>
      <Modal
        open={editingCred !== null}
        title={`Update Credential: ${editingCred?.name ?? ""}`}
        onCancel={() => {
          setEditingCred(null);
          updateCredForm.resetFields();
        }}
        footer={null}
      >
        <Typography.Text type="secondary" style={{ display: "block", marginBottom: 12 }}>
          Provide updated values. All secret fields will be re-encrypted. Previously stored values are not shown.
        </Typography.Text>
        <Form
          form={updateCredForm}
          layout="vertical"
          onFinish={(values) => {
            if (editingCred?.name) {
              try {
                const payload = normalizeCredentialPayload({ ...values, name: editingCred.name });
                updateCredMut.mutate({ name: editingCred.name, payload });
              } catch (err) {
                message.error("Invalid extra JSON");
              }
            }
          }}
        >
          <Form.Item name="credential_type" label="Type" initialValue="database">
            <Select options={[
              { label: "Database", value: "database" },
              { label: "API Key", value: "api_key" },
              { label: "Generic", value: "generic" },
            ]} />
          </Form.Item>
          <CredentialTypeFields />
          <Button type="primary" htmlType="submit" loading={updateCredMut.isPending}>
            Update
          </Button>
        </Form>
      </Modal>
      <Card title={`Import Jobs (active domain: ${importDomain})`}>
        <Space direction="vertical" style={{ width: "100%" }}>
          <Typography.Text type="secondary">Paste a job JSON (single object or array) or use the sample set.</Typography.Text>
          <Select
            style={{ minWidth: 200 }}
            placeholder="Set active domain"
            options={
              isAdmin
                ? (domainsQuery.data?.domains?.map((d) => ({ label: d.domain, value: d.domain })) ?? [])
                : [{ label: activeDomain, value: activeDomain }]
            }
            value={importDomain}
            onChange={(val) => {
              setImportDomain(val);
              setDomain(val);
              message.info(`Active domain set to ${val}`);
            }}
          />
          <Space>
            <Select
              placeholder="Pick a built-in template"
              style={{ minWidth: 220 }}
              value={selectedSample}
              onChange={(val) => {
                setSelectedSample(val);
              }}
              options={templatesQuery.data?.templates?.map((t) => ({ label: t.name, value: t.id })) ?? []}
              loading={templatesQuery.isLoading}
            />
            <Button
              onClick={async () => {
                if (!selectedSample) {
                  message.error("Choose a template first");
                  return;
                }
                try {
                  await importTemplate(selectedSample);
                  message.success("Template imported");
                  queryClient.invalidateQueries({ queryKey: ["jobs", activeDomain] });
                } catch (err) {
                  message.error((err as Error).message);
                }
              }}
            >
              Import Template
            </Button>
          </Space>
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
                const originalToken = getEffectiveToken();
                try {
                  const results = await Promise.allSettled(
                    jobs.map((j) =>
                      withTempToken(importToken || originalToken, () => createJob({ ...(j as any), domain: importDomain })),
                    ),
                  );
                  const ok = results.filter((r) => r.status === "fulfilled").length;
                  const fail = results.length - ok;
                  if (ok) message.success(`Imported ${ok} job(s)`);
                  if (fail) message.error(`${fail} job(s) failed`);
                  queryClient.invalidateQueries({ queryKey: ["jobs", activeDomain] });
                } finally {
                  if (originalToken) setTokenForDomain(localStorage.getItem("hydra_domain") || "prod", originalToken);
                  setImporting(false);
                }
              }}
            >
              Import
            </Button>
          </Space>
          <Typography.Text type="secondary">
            Use a domain token here to import into that domain (recommended), instead of using the admin token.
          </Typography.Text>
          <Input.Password
            placeholder="Domain token for import"
            value={importToken}
            onChange={(e) => setImportToken(e.target.value)}
          />
        </Space>
      </Card>
      <Modal
        open={tokenModal.open}
        footer={null}
        onCancel={() => setTokenModal({ open: false })}
        title={`Domain Token – ${tokenModal.domain}`}
        width={560}
      >
        <Space direction="vertical" style={{ width: "100%" }} size={12}>
          <Typography.Text strong>
            Copy this token. It will not be shown again.
          </Typography.Text>
          <Input.Password
            readOnly
            value={tokenModal.token ?? ""}
            style={{ fontFamily: "monospace" }}
          />
          <Button
            icon={<CopyOutlined />}
            onClick={() => {
              navigator.clipboard?.writeText(tokenModal.token ?? "");
              message.success("Token copied");
            }}
          >
            Copy Token
          </Button>
          <Divider style={{ margin: "4px 0" }} />
          <Typography.Text type="secondary">
            Ready-to-run startup command — token is substituted in:
          </Typography.Text>
          <CopyableCode code={`DOMAIN=${tokenModal.domain ?? activeDomain} API_TOKEN=${tokenModal.token ?? "<domain_token>"} \\
REDIS_URL=redis://<redis-host>:6379/0 \\
REDIS_PASSWORD=<worker_redis_acl_password> \\
docker compose -f docker-compose.worker.yml up -d --build`} />
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            Workers require <Typography.Text code>REDIS_PASSWORD</Typography.Text> by default (<Typography.Text code>WORKER_REQUIRE_REDIS_ACL=true</Typography.Text>) — the
            worker exits on startup without it. Run <Typography.Text code>Rotate Worker Redis ACL</Typography.Text> below to get a real value, or
            set <Typography.Text code>WORKER_REQUIRE_REDIS_ACL=false</Typography.Text> if this Redis instance has no ACL configured.
          </Typography.Text>
        </Space>
      </Modal>
      <Modal
        open={redisAclModal.open}
        footer={null}
        onCancel={() => setRedisAclModal({ open: false })}
        title={`Worker Redis ACL – ${redisAclModal.domain ?? activeDomain}`}
        width={580}
      >
        <Space direction="vertical" style={{ width: "100%" }} size={12}>
          <Typography.Text strong>
            Use these credentials for workers in this domain. They will not be shown again.
          </Typography.Text>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
            <div>
              <Typography.Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 4 }}>
                REDIS_PASSWORD
              </Typography.Text>
              <Input.Password
                readOnly
                value={redisAclModal.acl?.password ?? ""}
                style={{ fontFamily: "monospace" }}
              />
            </div>
            <div>
              <Typography.Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 4 }}>
                Redis Username
              </Typography.Text>
              <Input
                readOnly
                value={redisAclModal.acl?.username ?? redisAclModal.domain ?? activeDomain}
                style={{ fontFamily: "monospace" }}
              />
            </div>
          </div>
          <Button
            icon={<CopyOutlined />}
            onClick={() => {
              navigator.clipboard?.writeText(redisAclModal.acl?.password ?? "");
              message.success("Redis password copied");
            }}
          >
            Copy Password
          </Button>
          <Divider style={{ margin: "4px 0" }} />
          <Typography.Text type="secondary">
            Ready-to-run startup command — Redis password is substituted in:
          </Typography.Text>
          <CopyableCode code={`DOMAIN=${redisAclModal.domain ?? activeDomain} API_TOKEN=<domain_token> \\
REDIS_URL=redis://<redis-host>:6379/0 \\
REDIS_PASSWORD=${redisAclModal.acl?.password ?? "<redis_password>"} \\
docker compose -f docker-compose.worker.yml up -d --build`} />
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            Replace <Typography.Text code>{"<domain_token>"}</Typography.Text> with your domain token from above. The Redis username is automatically derived from <Typography.Text code>DOMAIN</Typography.Text>.
          </Typography.Text>
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
          setTokenForDomain(switchModal.domain, switchModal.token);
          setDomain(switchModal.domain);
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
