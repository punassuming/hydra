import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Col,
  Divider,
  Form,
  Input,
  InputNumber,
  Row,
  Select,
  Space,
  Switch,
  Typography,
  Steps,
} from "antd";
import { JobDefinition, PythonEnvironment } from "../types";
import { JobPayload, ValidationResult, fetchWorkers, generateJob } from "../api/jobs";

const defaultAffinity = {
  os: ["linux"],
  tags: [] as string[],
  allowed_users: [] as string[],
  hostnames: [] as string[],
  subnets: [] as string[],
  deployment_types: [] as string[],
};

const createDefaultPythonEnvironment = (): PythonEnvironment => ({
  type: "system",
  python_version: "python3",
  requirements: [],
  requirements_file: null,
  venv_path: null,
});

const createDefaultPythonExecutor = () => ({
  type: "python" as const,
  code: "# Add your Python here\nprint('hello')",
  interpreter: "python3",
  environment: createDefaultPythonEnvironment(),
});

const createDefaultPayload = (): JobPayload => ({
  name: "",
  user: "default",
  // queue removed
  priority: 5,
  affinity: {
    os: [...defaultAffinity.os],
    tags: [],
    allowed_users: [],
    hostnames: [],
    subnets: [],
    deployment_types: [],
  },
  executor: { type: "shell", script: "echo 'hello world'", shell: "bash" },
  retries: 0,
  timeout: 30,
  schedule: {
    mode: "immediate",
    enabled: true,
    cron: "",
    interval_seconds: 300,
    start_at: null,
    end_at: null,
    next_run_at: null,
    timezone: "UTC",
  },
  completion: {
    exit_codes: [0],
    stdout_contains: [],
    stdout_not_contains: [],
    stderr_contains: [],
    stderr_not_contains: [],
  },
});

interface Props {
  selectedJob?: JobDefinition | null;
  onSubmit: (payload: JobPayload) => Promise<void> | void;
  onValidate: (payload: JobPayload) => Promise<ValidationResult | undefined> | ValidationResult | undefined;
  onManualRun: () => void;
  onAdhocRun: (payload: JobPayload) => void;
  submitting: boolean;
  validating: boolean;
  statusMessage?: string;
  onReset: () => void;
}

export function JobForm({
  selectedJob,
  onSubmit,
  onValidate,
  onManualRun,
  onAdhocRun,
  submitting,
  validating,
  statusMessage,
  onReset,
}: Props) {
  const [payload, setPayload] = useState<JobPayload>(() => createDefaultPayload());
  const [activeStep, setActiveStep] = useState(0);
  const [prompt, setPrompt] = useState("");
  const [generating, setGenerating] = useState(false);
  const [provider, setProvider] = useState<"gemini" | "openai">("gemini");

  const workersQuery = useQuery({
    queryKey: ["workers"],
    queryFn: fetchWorkers,
    staleTime: 5000,
  });

  const workerHints = useMemo(() => {
    const workers = workersQuery.data ?? [];
    const collect = (getter: (w: any) => string | string[] | undefined) => {
      const values = workers.flatMap((w) => {
        const v = getter(w);
        if (!v) return [];
        return Array.isArray(v) ? v : [v];
      });
      return Array.from(new Set(values.filter(Boolean))) as string[];
    };
    return {
      os: collect((w) => w.os),
      tags: collect((w) => w.tags),
      users: collect((w) => w.allowed_users),
      hostnames: collect((w) => w.hostname),
      subnets: collect((w) => w.subnet),
      deployments: collect((w) => w.deployment_type),
      pythonVersions: collect((w) => w.python_version),
    };
  }, [workersQuery.data]);

  const normalizeExecutor = (exec: JobDefinition["executor"]): JobPayload["executor"] => {
    if (exec.type !== "python") {
      return exec as JobPayload["executor"];
    }
    return {
      ...exec,
      environment: {
        ...createDefaultPythonEnvironment(),
        python_version: exec.environment?.python_version ?? exec.interpreter ?? "python3",
        ...exec.environment,
        requirements: exec.environment?.requirements ?? [],
      },
    } as JobPayload["executor"];
  };

  const handleGenerate = async () => {
    if (!prompt.trim()) return;
    setGenerating(true);
    try {
      const generated = await generateJob(prompt, provider);
      if (generated) {
        setPayload({
            ...generated,
            executor: normalizeExecutor(generated.executor)
        });
      }
    } catch (e) {
      console.error("Failed to generate job", e);
    } finally {
      setGenerating(false);
    }
  };

  useEffect(() => {
    if (selectedJob) {
      setPayload({
        name: selectedJob.name,
        user: selectedJob.user || "default",
        affinity: { ...createDefaultPayload().affinity, ...selectedJob.affinity },
        executor: normalizeExecutor(selectedJob.executor),
        retries: selectedJob.retries,
        timeout: selectedJob.timeout,
        // queue removed
        priority: (selectedJob as any).priority ?? 5,
        schedule: { ...createDefaultPayload().schedule, ...(selectedJob.schedule ?? {}) },
        completion: { ...createDefaultPayload().completion, ...(selectedJob.completion ?? {}) },
      });
    } else {
      setPayload(createDefaultPayload());
    }
    setActiveStep(0);
  }, [selectedJob]);

  const executor = payload.executor;
  const executorType = executor.type;
  const schedule = payload.schedule;
  const completion = payload.completion;
  const pythonEnv =
    executor.type === "python"
      ? { ...createDefaultPythonEnvironment(), ...(executor.environment as PythonEnvironment | undefined) }
      : null;

  const updatePayload = (field: keyof JobPayload, value: any) => {
    setPayload((prev) => ({ ...prev, [field]: value }));
  };

  const updateExecutor = (update: Record<string, unknown>) => {
    setPayload((prev) => ({ ...prev, executor: { ...prev.executor, ...update } as JobPayload["executor"] }));
  };

  const updateSchedule = (update: Record<string, unknown>) => {
    setPayload((prev) => ({ ...prev, schedule: { ...prev.schedule, ...update } }));
  };

  const updateCompletion = (update: Record<string, unknown>) => {
    setPayload((prev) => ({ ...prev, completion: { ...prev.completion, ...update } }));
  };

  const updatePythonEnv = (update: Partial<PythonEnvironment>) => {
    if (executor.type !== "python") {
      return;
    }
    const merged = {
      ...createDefaultPythonEnvironment(),
      ...(executor.environment as PythonEnvironment | undefined),
      ...update,
    };
    updateExecutor({ environment: merged });
  };

  const updateAffinity = (key: keyof typeof defaultAffinity, value: string[]) => {
    updatePayload("affinity", {
      ...payload.affinity,
      [key]: value,
    });
  };

  const parseList = (value: string) =>
    value
      .split(/\n|,/)
      .map((s) => s.trim())
      .filter(Boolean);

  const setCompletionList = (field: keyof JobPayload["completion"], value: string) => {
    updateCompletion({ [field]: parseList(value) });
  };

  const toInputValue = (iso?: string | null) => (iso ? new Date(iso).toISOString().slice(0, 16) : "");
  const fromInputValue = (value: string) => (value ? new Date(value).toISOString() : null);

  const handleValidateOnly = async () => onValidate(payload);

  const handleValidateThenSubmit = async () => {
    const validation = await onValidate(payload);
    if (!validation?.valid) {
      return;
    }
    const normalized = { ...payload, user: payload.user?.trim() || "default" };
    await onSubmit(normalized);
  };

  const executorTypeSelect = (
    <Form.Item label="Executor Type" required>
      <Select
        value={executorType}
        onChange={(nextType) => {
          const defaults: Record<string, any> = {
            python: createDefaultPythonExecutor(),
            shell: { type: "shell", script: "echo 'hello world'", shell: "bash" },
            batch: { type: "batch", script: "echo hello", shell: "cmd" },
            external: { type: "external", command: "/usr/bin/env" },
          };
          updateExecutor(defaults[nextType]);
        }}
        options={[
          { label: "Shell", value: "shell" },
          { label: "Batch", value: "batch" },
          { label: "Python", value: "python" },
          { label: "External Binary", value: "external" },
        ]}
      />
    </Form.Item>
  );

  const steps = [
    { key: "basics", title: "Basics", description: "Name, retries, timeout" },
    { key: "executor", title: "Executor", description: "Code & environment" },
    { key: "schedule", title: "Schedule", description: "When it should run" },
    { key: "affinity", title: "Placement", description: "Workers & affinity" },
    { key: "completion", title: "Completion", description: "Success signals" },
  ];

  const renderStepContent = (key: string) => {
    switch (key) {
      case "executor":
        return (
          <>
            <Row gutter={16}>
              <Col xs={24} md={12}>
                {executorTypeSelect}
              </Col>
              <Col xs={24} md={12}>
                <Form.Item label="Arguments">
                  <Input
                    value={(executor as any).args?.join(" ") ?? ""}
                    onChange={(e) => updateExecutor({ args: e.target.value.split(" ").filter(Boolean) })}
                    placeholder="--flag value"
                  />
                </Form.Item>
              </Col>
            </Row>

            {executor.type === "python" && (
              <>
                <Row gutter={16}>
                  <Col xs={24} md={12}>
                    <Form.Item label="Interpreter">
                      <Select
                        mode="tags"
                        value={executor.interpreter ? [executor.interpreter] : []}
                        onChange={(val) => {
                          const arr = Array.isArray(val) ? val : [val];
                          updateExecutor({ interpreter: arr[arr.length - 1] });
                        }}
                        options={(workerHints.pythonVersions ?? []).map((v) => ({ label: v, value: v }))}
                        placeholder="python3, python3.11, uv"
                      />
                    </Form.Item>
                  </Col>
                  <Col xs={24} md={12}>
                    <Form.Item label="Python Version / Dist (uv friendly)">
                      <Select
                        mode="tags"
                        value={pythonEnv?.python_version ? [pythonEnv.python_version] : []}
                        onChange={(val) => {
                          const arr = Array.isArray(val) ? val : [val];
                          updatePythonEnv({ python_version: arr[arr.length - 1] });
                        }}
                        options={(workerHints.pythonVersions ?? []).map((v) => ({ label: v, value: v }))}
                        placeholder="3.11, 3.12, pypy3"
                      />
                    </Form.Item>
                  </Col>
                </Row>
                <Form.Item label="Python Code Block">
                  <Input.TextArea
                    value={executor.code ?? ""}
                    onChange={(e) => updateExecutor({ code: e.target.value })}
                    autoSize={{ minRows: 8 }}
                    placeholder="# Multi-line Python supported"
                  />
                </Form.Item>
                {pythonEnv && (
                  <Row gutter={16}>
                    <Col xs={24} md={8}>
                      <Form.Item label="Environment Type">
                        <Select
                          value={pythonEnv.type}
                          onChange={(value) => updatePythonEnv({ type: value as PythonEnvironment["type"] })}
                          options={[
                            { label: "System", value: "system" },
                            { label: "Virtualenv", value: "venv" },
                            { label: "uv managed", value: "uv" },
                          ]}
                        />
                      </Form.Item>
                    </Col>
                    <Col xs={24} md={8}>
                      <Form.Item label="Virtualenv Path (optional)">
                        <Input
                          value={pythonEnv.venv_path ?? ""}
                          onChange={(e) => updatePythonEnv({ venv_path: e.target.value || null })}
                          placeholder="/opt/venvs/job"
                        />
                      </Form.Item>
                    </Col>
                    <Col xs={24} md={8}>
                      <Form.Item label="Requirements File">
                        <Input
                          value={pythonEnv.requirements_file ?? ""}
                          onChange={(e) => updatePythonEnv({ requirements_file: e.target.value || null })}
                          placeholder="/workspace/requirements.txt"
                        />
                      </Form.Item>
                    </Col>
                    <Col xs={24} md={12}>
                      <Form.Item label="Requirements (one per line)">
                        <Input.TextArea
                          value={(pythonEnv.requirements ?? []).join("\n")}
                          onChange={(e) => updatePythonEnv({ requirements: parseList(e.target.value) })}
                          autoSize
                        />
                      </Form.Item>
                    </Col>
                    <Col xs={24} md={12}>
                      <Form.Item label="Working Directory">
                        <Input
                          value={executor.workdir ?? ""}
                          onChange={(e) => updateExecutor({ workdir: e.target.value || null })}
                          placeholder="/opt/jobs"
                        />
                      </Form.Item>
                    </Col>
                    {pythonEnv.type === "uv" && (
                      <Col span={24}>
                        <Alert
                          type="info"
                          showIcon
                          message="Workers should have uv installed. The requested Python version will be provisioned via uv if available."
                        />
                      </Col>
                    )}
                  </Row>
                )}
              </>
            )}

            {(executor.type === "shell" || executor.type === "batch") && (
              <>
                <Row gutter={16}>
                  <Col xs={24} md={12}>
                    <Form.Item label="Shell">
                      <Input
                        value={executor.shell ?? (executor.type === "batch" ? "cmd" : "bash")}
                        onChange={(e) => updateExecutor({ shell: e.target.value })}
                      />
                    </Form.Item>
                  </Col>
                  <Col xs={24} md={12}>
                    <Form.Item label="Working Directory">
                      <Input
                        value={executor.workdir ?? ""}
                        onChange={(e) => updateExecutor({ workdir: e.target.value || null })}
                        placeholder="/opt/jobs"
                      />
                    </Form.Item>
                  </Col>
                </Row>
                <Form.Item label="Script / Code Block">
                  <Input.TextArea
                    value={executor.script ?? ""}
                    onChange={(e) => updateExecutor({ script: e.target.value })}
                    autoSize={{ minRows: 8 }}
                    placeholder="Multi-line shell or batch scripts supported"
                  />
                </Form.Item>
              </>
            )}

            {executor.type === "external" && (
              <>
                <Form.Item label="Command / Binary Path">
                  <Input value={executor.command ?? ""} onChange={(e) => updateExecutor({ command: e.target.value })} />
                </Form.Item>
                <Form.Item label="Working Directory">
                  <Input
                    value={executor.workdir ?? ""}
                    onChange={(e) => updateExecutor({ workdir: e.target.value || null })}
                    placeholder="/opt/jobs"
                  />
                </Form.Item>
              </>
            )}

            <Form.Item label="Environment Variables (KEY=VALUE per line)">
              <Input.TextArea
                value={
                  executor.env
                    ? Object.entries(executor.env)
                        .map(([k, v]) => `${k}=${v}`)
                        .join("\n")
                    : ""
                }
                onChange={(e) => {
                  const envLines = e.target.value.split("\n");
                  const env: Record<string, string> = {};
                  envLines.forEach((line) => {
                    const [k, ...rest] = line.split("=");
                    if (k && rest.length) {
                      env[k.trim()] = rest.join("=").trim();
                    }
                  });
                  updateExecutor({ env });
                }}
                autoSize
              />
            </Form.Item>
          </>
        );
      case "schedule":
        return (
          <>
            <Row gutter={16} align="middle">
              <Col xs={24} md={8}>
                <Form.Item label="Mode">
                  <Select
                    value={schedule.mode}
                    onChange={(mode) => updateSchedule({ mode, next_run_at: null })}
                    options={[
                      { label: "Immediate", value: "immediate" },
                      { label: "Interval", value: "interval" },
                      { label: "Cron", value: "cron" },
                    ]}
                  />
                </Form.Item>
              </Col>
              <Col xs={24} md={8}>
                <Form.Item label="Enabled">
                  <Switch checked={schedule.enabled} onChange={(checked) => updateSchedule({ enabled: checked })} />
                </Form.Item>
              </Col>
              <Col xs={24} md={8}>
                <Typography.Text type="secondary">
                  Next run:{" "}
                  {!schedule.enabled
                    ? "Disabled"
                    : schedule.next_run_at
                      ? new Date(schedule.next_run_at).toLocaleString()
                      : schedule.mode === "immediate"
                        ? "Immediately"
                        : "Pending"}
                </Typography.Text>
              </Col>
            </Row>
            {schedule.mode === "interval" && (
              <Row gutter={16}>
                <Col xs={24} md={12}>
                  <Form.Item label="Interval (seconds)">
                    <InputNumber
                      min={1}
                      style={{ width: "100%" }}
                      value={schedule.interval_seconds ?? 300}
                      onChange={(value) => updateSchedule({ interval_seconds: Number(value) })}
                    />
                  </Form.Item>
                </Col>
              </Row>
            )}
            {schedule.mode === "cron" && (
              <Row gutter={16}>
                <Col span={24}>
                  <Form.Item label="Cron Expression">
                    <Input value={schedule.cron ?? ""} onChange={(e) => updateSchedule({ cron: e.target.value })} placeholder="*/5 * * * *" />
                  </Form.Item>
                </Col>
              </Row>
            )}
            {(schedule.mode === "interval" || schedule.mode === "cron") && (
              <Row gutter={16}>
                <Col xs={24} md={12}>
                  <Form.Item label="Start At">
                    <Input
                      type="datetime-local"
                      value={toInputValue(schedule.start_at)}
                      onChange={(e) => updateSchedule({ start_at: fromInputValue(e.target.value) })}
                    />
                  </Form.Item>
                </Col>
                <Col xs={24} md={12}>
                  <Form.Item label="End At">
                    <Input
                      type="datetime-local"
                      value={toInputValue(schedule.end_at)}
                      onChange={(e) => updateSchedule({ end_at: fromInputValue(e.target.value) })}
                    />
                  </Form.Item>
                </Col>
              </Row>
            )}
          </>
        );
      case "completion":
        return (
          <>
            <Row gutter={16}>
              <Col span={24}>
                <Form.Item label="Exit Codes">
                  <Input
                    value={completion.exit_codes.join(", ")}
                    onChange={(e) => {
                      const values = parseList(e.target.value)
                        .map((c) => Number(c))
                        .filter((n) => !Number.isNaN(n));
                      updateCompletion({ exit_codes: values.length ? values : [] });
                    }}
                    placeholder="0, 2"
                  />
                </Form.Item>
              </Col>
            </Row>
            <Row gutter={16}>
              <Col xs={24} md={12}>
                <Form.Item label="Stdout must contain">
                  <Input.TextArea
                    value={completion.stdout_contains.join("\n")}
                    onChange={(e) => setCompletionList("stdout_contains", e.target.value)}
                    placeholder="ready"
                    autoSize
                  />
                </Form.Item>
              </Col>
              <Col xs={24} md={12}>
                <Form.Item label="Stdout must NOT contain">
                  <Input.TextArea
                    value={completion.stdout_not_contains.join("\n")}
                    onChange={(e) => setCompletionList("stdout_not_contains", e.target.value)}
                    placeholder="error"
                    autoSize
                  />
                </Form.Item>
              </Col>
            </Row>
            <Row gutter={16}>
              <Col xs={24} md={12}>
                <Form.Item label="Stderr must contain">
                  <Input.TextArea
                    value={completion.stderr_contains.join("\n")}
                    onChange={(e) => setCompletionList("stderr_contains", e.target.value)}
                    autoSize
                  />
                </Form.Item>
              </Col>
              <Col xs={24} md={12}>
                <Form.Item label="Stderr must NOT contain">
                  <Input.TextArea
                    value={completion.stderr_not_contains.join("\n")}
                    onChange={(e) => setCompletionList("stderr_not_contains", e.target.value)}
                    autoSize
                  />
                </Form.Item>
              </Col>
            </Row>
          </>
        );
      case "affinity":
        return (
          <>
            <Alert
              type="info"
              showIcon
              message="Use the worker-derived dropdowns to target specific pools. You can also type new values to create ad-hoc affinities."
              style={{ marginBottom: 12 }}
            />
            <Row gutter={16}>
              <Col xs={24} md={8}>
                <Form.Item label="Target OS">
                  <Select
                    mode="tags"
                    value={payload.affinity.os}
                    onChange={(vals) => updateAffinity("os", vals)}
                    options={workerHints.os.map((v) => ({ label: v, value: v }))}
                    placeholder="linux, windows"
                  />
                </Form.Item>
              </Col>
              <Col xs={24} md={8}>
                <Form.Item label="Tags">
                  <Select
                    mode="tags"
                    value={payload.affinity.tags}
                    onChange={(vals) => updateAffinity("tags", vals)}
                    options={workerHints.tags.map((v) => ({ label: v, value: v }))}
                    placeholder="gpu, python, ingest"
                  />
                </Form.Item>
              </Col>
              <Col xs={24} md={8}>
                <Form.Item label="Allowed Users">
                  <Select
                    mode="tags"
                    value={payload.affinity.allowed_users}
                    onChange={(vals) => updateAffinity("allowed_users", vals)}
                    options={workerHints.users.map((v) => ({ label: v, value: v }))}
                    placeholder="alice, bob"
                  />
                </Form.Item>
              </Col>
            </Row>
            <Row gutter={16}>
              <Col xs={24} md={8}>
                <Form.Item label="Hostnames">
                  <Select
                    mode="tags"
                    value={payload.affinity.hostnames ?? []}
                    onChange={(vals) => updateAffinity("hostnames", vals)}
                    options={workerHints.hostnames.map((v) => ({ label: v, value: v }))}
                    placeholder="worker-1, batch-2"
                  />
                </Form.Item>
              </Col>
              <Col xs={24} md={8}>
                <Form.Item label="Subnets / CIDRs">
                  <Select
                    mode="tags"
                    value={payload.affinity.subnets ?? []}
                    onChange={(vals) => updateAffinity("subnets", vals)}
                    options={workerHints.subnets.map((v) => ({ label: v, value: v }))}
                    placeholder="10.0.1"
                  />
                </Form.Item>
              </Col>
              <Col xs={24} md={8}>
                <Form.Item label="Deployment Types">
                  <Select
                    mode="tags"
                    value={payload.affinity.deployment_types ?? []}
                    onChange={(vals) => updateAffinity("deployment_types", vals)}
                    options={workerHints.deployments.map((v) => ({ label: v, value: v }))}
                    placeholder="docker, kubernetes, bare-metal"
                  />
                </Form.Item>
              </Col>
            </Row>
          </>
        );
      case "basics":
      default:
        return (
          <>
            <Row gutter={16}>
              <Col xs={24} md={12}>
                <Form.Item label="Name" required>
                  <Input value={payload.name} onChange={(e) => updatePayload("name", e.target.value)} placeholder="batch-import" />
                </Form.Item>
              </Col>
            </Row>
            <Row gutter={16}>
              <Col xs={24} md={12}>
                <Form.Item label="Timeout (seconds)">
                  <InputNumber
                    min={0}
                    style={{ width: "100%" }}
                    value={payload.timeout}
                    onChange={(value) => updatePayload("timeout", Number(value))}
                  />
                </Form.Item>
              </Col>
              <Col xs={24} md={12}>
                <Form.Item label="Retries">
                  <InputNumber
                    min={0}
                    style={{ width: "100%" }}
                    value={payload.retries}
                    onChange={(value) => updatePayload("retries", Number(value))}
                  />
                </Form.Item>
              </Col>
              <Col xs={24} md={12}>
                <Form.Item label="Priority (higher runs first)">
                  <InputNumber
                    min={0}
                    max={100}
                    style={{ width: "100%" }}
                    value={payload.priority}
                    onChange={(value) => updatePayload("priority", Number(value))}
                  />
                </Form.Item>
              </Col>
            </Row>
          </>
        );
    }
  };

  const activeKey = steps[activeStep]?.key ?? "basics";

  return (
    <Form layout="vertical" onFinish={handleValidateThenSubmit}>
      {!selectedJob && (
        <Alert
            message="Magic Job Generator"
            description={
                <Space.Compact style={{ width: '100%' }}>
                    <Select 
                        value={provider} 
                        onChange={setProvider} 
                        options={[{label: 'Gemini', value: 'gemini'}, {label: 'OpenAI', value: 'openai'}]}
                        style={{ width: 100 }}
                    />
                    <Input 
                        placeholder="Describe your job (e.g., 'Run a backup script every Sunday at 2am')" 
                        value={prompt}
                        onChange={e => setPrompt(e.target.value)}
                        onPressEnter={handleGenerate}
                    />
                    <Button type="primary" loading={generating} onClick={handleGenerate}>Generate</Button>
                </Space.Compact>
            }
            type="info"
            showIcon
            style={{ marginBottom: 20 }}
        />
      )}
      <Steps
        current={activeStep}
        items={steps}
        onChange={setActiveStep}
        responsive
      />
      <Divider />
      <Space direction="vertical" size="large" style={{ width: "100%" }}>
        {renderStepContent(activeKey)}
      </Space>
      <Divider />
      <Space wrap>
        {activeStep > 0 && (
          <Button onClick={() => setActiveStep((prev) => Math.max(0, prev - 1))}>
            Previous
          </Button>
        )}
        {activeStep < steps.length - 1 && (
          <Button type="primary" onClick={() => setActiveStep((prev) => Math.min(steps.length - 1, prev + 1))}>
            Next
          </Button>
        )}
        {activeStep === steps.length - 1 && (
          <Button type="primary" htmlType="submit" loading={submitting || validating}>
            {selectedJob ? "Validate & Update" : "Validate & Submit"}
          </Button>
        )}
        <Button onClick={handleValidateOnly} loading={validating}>
          Validate This Step
        </Button>
        {!selectedJob && (
          <Button
            onClick={() => {
              const normalized = { ...payload, user: payload.user?.trim() || "default" };
              onAdhocRun(normalized);
            }}
            disabled={submitting}
            type="dashed"
          >
            Run Adhoc
          </Button>
        )}
        {selectedJob && (
          <Button onClick={onManualRun} type="default">
            Run Now
          </Button>
        )}
        {selectedJob && (
          <Button onClick={onReset} danger>
            New Job
          </Button>
        )}
      </Space>
      {statusMessage && <Typography.Paragraph style={{ marginTop: "0.5rem" }}>{statusMessage}</Typography.Paragraph>}
    </Form>
  );
}
