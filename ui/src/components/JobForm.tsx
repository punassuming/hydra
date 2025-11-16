import { useEffect, useMemo, useState } from "react";
import { Form, Input, InputNumber, Select, Switch, Button, Divider, Space, Typography, Row, Col, Alert } from "antd";
import { JobDefinition, PythonEnvironment } from "../types";
import { JobPayload } from "../api/jobs";

const createDefaultPythonEnvironment = (): PythonEnvironment => ({
  type: "system",
  python_version: "python3",
  requirements: [],
  requirements_file: null,
  venv_path: null,
});

const createDefaultPythonExecutor = () => ({
  type: "python" as const,
  code: "print('hello')",
  interpreter: "python3",
  environment: createDefaultPythonEnvironment(),
});

const createDefaultPayload = (): JobPayload => ({
  name: "",
  user: "",
  affinity: { os: ["linux"], tags: [], allowed_users: [] },
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
  onSubmit: (payload: JobPayload) => void;
  onValidate: (payload: JobPayload) => void;
  onManualRun: () => void;
  onAdhocRun: (payload: JobPayload) => void;
  submitting: boolean;
  validating: boolean;
  statusMessage?: string;
  onReset: () => void;
}

export function JobForm({ selectedJob, onSubmit, onValidate, onManualRun, onAdhocRun, submitting, validating, statusMessage, onReset }: Props) {
  const [payload, setPayload] = useState<JobPayload>(() => createDefaultPayload());

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

  useEffect(() => {
    if (selectedJob) {
      setPayload({
        name: selectedJob.name,
        user: selectedJob.user,
        affinity: selectedJob.affinity,
        executor: normalizeExecutor(selectedJob.executor),
        retries: selectedJob.retries,
        timeout: selectedJob.timeout,
        schedule: selectedJob.schedule ?? createDefaultPayload().schedule,
        completion: selectedJob.completion ?? createDefaultPayload().completion,
      });
    } else {
      setPayload(createDefaultPayload());
    }
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
    const merged = { ...createDefaultPythonEnvironment(), ...(executor.environment as PythonEnvironment | undefined), ...update };
    updateExecutor({ environment: merged });
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

  const handleSubmit = () => {
    onSubmit(payload);
  };

  const handleValidate = () => onValidate(payload);

  const affinityDisplay = useMemo(
    () => ({
      os: payload.affinity.os.join(","),
      tags: payload.affinity.tags.join(","),
      allowed_users: payload.affinity.allowed_users.join(","),
    }),
    [payload.affinity],
  );

  const setAffinity = (key: keyof typeof affinityDisplay, value: string) => {
    updatePayload("affinity", {
      ...payload.affinity,
      [key]: value
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
    });
  };

  return (
    <Form layout="vertical" onFinish={handleSubmit}>
      <Row gutter={16}>
        <Col xs={24} md={12}>
          <Form.Item label="Name">
            <Input value={payload.name} onChange={(e) => updatePayload("name", e.target.value)} required />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item label="User">
            <Input value={payload.user} onChange={(e) => updatePayload("user", e.target.value)} required />
          </Form.Item>
        </Col>
      </Row>
      <Row gutter={16}>
        <Col xs={24} md={12}>
          <Form.Item label="Timeout (seconds)">
            <InputNumber min={0} style={{ width: "100%" }} value={payload.timeout} onChange={(value) => updatePayload("timeout", Number(value))} />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item label="Retries">
            <InputNumber min={0} style={{ width: "100%" }} value={payload.retries} onChange={(value) => updatePayload("retries", Number(value))} />
          </Form.Item>
        </Col>
      </Row>

      <Divider orientation="left">Affinity</Divider>
      <Row gutter={16}>
        <Col xs={24} md={8}>
          <Form.Item label="Target OS (comma separated)">
            <Input value={affinityDisplay.os} onChange={(e) => setAffinity("os", e.target.value)} placeholder="linux,windows" />
          </Form.Item>
        </Col>
        <Col xs={24} md={8}>
          <Form.Item label="Tags">
            <Input value={affinityDisplay.tags} onChange={(e) => setAffinity("tags", e.target.value)} placeholder="gpu,python" />
          </Form.Item>
        </Col>
        <Col xs={24} md={8}>
          <Form.Item label="Allowed Users">
            <Input value={affinityDisplay.allowed_users} onChange={(e) => setAffinity("allowed_users", e.target.value)} placeholder="alice,bob" />
          </Form.Item>
        </Col>
      </Row>

      <Divider orientation="left">Schedule</Divider>
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
              <Input type="datetime-local" value={toInputValue(schedule.start_at)} onChange={(e) => updateSchedule({ start_at: fromInputValue(e.target.value) })} />
            </Form.Item>
          </Col>
          <Col xs={24} md={12}>
            <Form.Item label="End At">
              <Input type="datetime-local" value={toInputValue(schedule.end_at)} onChange={(e) => updateSchedule({ end_at: fromInputValue(e.target.value) })} />
            </Form.Item>
          </Col>
        </Row>
      )}

      <Divider orientation="left">Completion Criteria</Divider>
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
            <Input.TextArea value={completion.stdout_contains.join("\n")} onChange={(e) => setCompletionList("stdout_contains", e.target.value)} placeholder="ready" autoSize />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item label="Stdout must NOT contain">
            <Input.TextArea value={completion.stdout_not_contains.join("\n")} onChange={(e) => setCompletionList("stdout_not_contains", e.target.value)} placeholder="error" autoSize />
          </Form.Item>
        </Col>
      </Row>
      <Row gutter={16}>
        <Col xs={24} md={12}>
          <Form.Item label="Stderr must contain">
            <Input.TextArea value={completion.stderr_contains.join("\n")} onChange={(e) => setCompletionList("stderr_contains", e.target.value)} autoSize />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item label="Stderr must NOT contain">
            <Input.TextArea value={completion.stderr_not_contains.join("\n")} onChange={(e) => setCompletionList("stderr_not_contains", e.target.value)} autoSize />
          </Form.Item>
        </Col>
      </Row>

      <Divider orientation="left">Executor</Divider>
      <Row gutter={16}>
        <Col xs={24} md={12}>
          <Form.Item label="Executor Type">
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
        </Col>
        <Col xs={24} md={12}>
          <Form.Item label="Arguments">
            <Input value={(executor.args ?? []).join(" ")} onChange={(e) => updateExecutor({ args: e.target.value.split(" ").filter(Boolean) })} placeholder="--flag value" />
          </Form.Item>
        </Col>
      </Row>

      {executor.type === "python" && (
        <>
          <Form.Item label="Interpreter">
            <Input value={executor.interpreter ?? "python3"} onChange={(e) => updateExecutor({ interpreter: e.target.value })} />
          </Form.Item>
          <Form.Item label="Python Code">
            <Input.TextArea value={executor.code ?? ""} onChange={(e) => updateExecutor({ code: e.target.value })} autoSize />
          </Form.Item>
          {pythonEnv && (
            <Row gutter={16}>
              <Col span={24}>
                <Typography.Title level={5}>Python Environment</Typography.Title>
              </Col>
              <Col xs={24} md={8}>
                <Form.Item label="Environment Type">
                  <Select
                    value={pythonEnv.type}
                    onChange={(value) => updatePythonEnv({ type: value as PythonEnvironment["type"] })}
                    options={[
                      { label: "System", value: "system" },
                      { label: "Virtualenv", value: "venv" },
                      { label: "uv", value: "uv" },
                    ]}
                  />
                </Form.Item>
              </Col>
              <Col xs={24} md={8}>
                <Form.Item label="Python Version">
                  <Input value={pythonEnv.python_version ?? ""} onChange={(e) => updatePythonEnv({ python_version: e.target.value || null })} placeholder="3.11" />
                </Form.Item>
              </Col>
              {pythonEnv.type === "venv" && (
                <Col xs={24} md={8}>
                  <Form.Item label="Virtualenv Path">
                    <Input value={pythonEnv.venv_path ?? ""} onChange={(e) => updatePythonEnv({ venv_path: e.target.value || null })} placeholder="/opt/venvs/job" />
                  </Form.Item>
                </Col>
              )}
              <Col xs={24} md={12}>
                <Form.Item label="Requirements (one per line)">
                  <Input.TextArea value={(pythonEnv.requirements ?? []).join("\n")} onChange={(e) => updatePythonEnv({ requirements: parseList(e.target.value) })} autoSize />
                </Form.Item>
              </Col>
              <Col xs={24} md={12}>
                <Form.Item label="Requirements File">
                  <Input value={pythonEnv.requirements_file ?? ""} onChange={(e) => updatePythonEnv({ requirements_file: e.target.value || null })} placeholder="/workspace/requirements.txt" />
                </Form.Item>
              </Col>
              {pythonEnv.type === "uv" && (
                <Col span={24}>
                  <Alert type="info" showIcon message="Workers must have the uv CLI installed to run this job." />
                </Col>
              )}
            </Row>
          )}
        </>
      )}

      {(executor.type === "shell" || executor.type === "batch") && (
        <Row gutter={16}>
          <Col xs={24} md={12}>
            <Form.Item label="Shell">
              <Input value={executor.shell ?? (executor.type === "batch" ? "cmd" : "bash")} onChange={(e) => updateExecutor({ shell: e.target.value })} />
            </Form.Item>
          </Col>
          <Col span={24}>
            <Form.Item label="Script">
              <Input.TextArea value={executor.script ?? ""} onChange={(e) => updateExecutor({ script: e.target.value })} autoSize />
            </Form.Item>
          </Col>
        </Row>
      )}

      {executor.type === "external" && (
        <Form.Item label="Command / Binary Path">
          <Input value={executor.command ?? ""} onChange={(e) => updateExecutor({ command: e.target.value })} />
        </Form.Item>
      )}

      <Form.Item label="Working Directory">
        <Input value={executor.workdir ?? ""} onChange={(e) => updateExecutor({ workdir: e.target.value || null })} placeholder="/opt/jobs" />
      </Form.Item>

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

      <Divider />
      <Space wrap>
        <Button type="primary" htmlType="submit" loading={submitting}>
          {selectedJob ? "Update Job" : "Submit Job"}
        </Button>
        <Button onClick={handleValidate} loading={validating}>
          Validate
        </Button>
        {!selectedJob && (
          <Button onClick={() => onAdhocRun(payload)} disabled={submitting} type="dashed">
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
