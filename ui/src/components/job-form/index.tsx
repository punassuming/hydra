import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Col,
  Collapse,
  Divider,
  Form,
  Input,
  InputNumber,
  Row,
  Select,
  Space,
  Switch,
  Typography,
} from "antd";
import { JobDefinition, PythonEnvironment, SourceConfig } from "../../types";
import { JobPayload, ValidationResult, fetchWorkers, fetchJobs, generateJob } from "../../api/jobs";
import { useActiveDomain } from "../../context/ActiveDomainContext";
import { ProviderSelect } from "../ProviderSelect";
import {
  createDefaultPayload,
  createDefaultPythonEnvironment,
  createDefaultPythonExecutor,
  defaultAffinity,
  EXECUTOR_DEFAULTS,
  FormScheduleMode,
  parseList,
  WorkerHints,
} from "./defaults";
import { PlacementSection } from "./PlacementSection";
import { CompletionSection } from "./CompletionSection";
import { NotificationsSection } from "./NotificationsSection";
import { AuthSection } from "./AuthSection";
import { SourceSection } from "./SourceSection";
import { RetryAdvancedSection } from "./RetryAdvancedSection";
import { MiscSection } from "./MiscSection";

interface Props {
  selectedJob?: JobDefinition | null;
  /** Pre-populate the form from a template when creating a new job. Ignored when selectedJob is set. */
  templatePayload?: Partial<JobPayload> | null;
  onSubmit: (payload: JobPayload) => Promise<void> | void;
  onValidate: (payload: JobPayload) => Promise<ValidationResult | undefined> | ValidationResult | undefined;
  onManualRun: () => void;
  onAdhocRun: (payload: JobPayload) => void;
  submitting: boolean;
  validating: boolean;
  statusMessage?: string;
  onReset: () => void;
  onCancel?: () => void;
}

export function JobForm({
  selectedJob,
  templatePayload,
  onSubmit,
  onValidate,
  onManualRun,
  onAdhocRun,
  submitting,
  validating,
  statusMessage,
  onReset,
  onCancel,
}: Props) {
  const { domain } = useActiveDomain();
  const [payload, setPayload] = useState<JobPayload>(() => createDefaultPayload());
  const [prompt, setPrompt] = useState("");
  const [generating, setGenerating] = useState(false);
  const [provider, setProvider] = useState<"gemini" | "openai">("gemini");
  const [formScheduleMode, setFormScheduleMode] = useState<FormScheduleMode>("immediate");
  const [importError, setImportError] = useState<string>();
  const [lastValidation, setLastValidation] = useState<ValidationResult | undefined>();
  const [notifyWebhookEnabled, setNotifyWebhookEnabled] = useState(false);
  const [notifyEmailEnabled, setNotifyEmailEnabled] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [userModifiedFields] = useState<Set<string>>(() => new Set());
  const importInputRef = useRef<HTMLInputElement>(null);

  const workersQuery = useQuery({
    queryKey: ["workers", domain],
    queryFn: fetchWorkers,
    staleTime: 5000,
  });

  const jobsQuery = useQuery({
    queryKey: ["jobs", domain],
    queryFn: () => fetchJobs(),
    staleTime: 30000,
  });

  const allJobs = jobsQuery.data ?? [];

  const workerHints: WorkerHints = useMemo(() => {
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
      capabilities: collect((w) => w.capabilities),
      shells: collect((w) => w.shells),
    };
  }, [workersQuery.data]);

  const normalizeExecutor = (exec: JobDefinition["executor"]): JobPayload["executor"] => {
    if (exec.type === "batch" || exec.type === "powershell") {
      // Keep batch/powershell as-is — they are now first-class executor types in the form.
      return exec as JobPayload["executor"];
    }
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
        const nextPayload = {
          ...generated,
          executor: normalizeExecutor(generated.executor),
        };
        setPayload(nextPayload);
        setFormScheduleMode(
          (nextPayload.depends_on?.length ?? 0) > 0 && nextPayload.schedule.mode === "immediate"
            ? "dependency"
            : (nextPayload.schedule.mode as FormScheduleMode),
        );
        // Auto-expand advanced if AI generated non-default values
        if (hasNonDefaultAdvanced(nextPayload)) setShowAdvanced(true);
      }
    } catch (e) {
      console.error("Failed to generate job", e);
    } finally {
      setGenerating(false);
    }
  };

  /** Detect if any advanced fields have non-default values. */
  const hasNonDefaultAdvanced = (p: JobPayload) => {
    return (
      (p.affinity.hostnames?.length ?? 0) > 0 ||
      (p.affinity.subnets?.length ?? 0) > 0 ||
      (p.affinity.deployment_types?.length ?? 0) > 0 ||
      (p.affinity.allowed_users?.length ?? 0) > 0 ||
      p.completion.exit_codes.length !== 1 ||
      p.completion.exit_codes[0] !== 0 ||
      p.completion.stdout_contains.length > 0 ||
      p.completion.stdout_not_contains.length > 0 ||
      p.completion.stderr_contains.length > 0 ||
      p.completion.stderr_not_contains.length > 0 ||
      (p.on_failure_webhooks?.length ?? 0) > 0 ||
      (p.on_failure_email_to?.length ?? 0) > 0 ||
      !!(p.executor as any).impersonate_user ||
      !!(p.executor as any).kerberos?.principal ||
      !!p.source ||
      (p.retries ?? 0) > 0 ||
      (p.max_retries ?? 0) > 0 ||
      p.priority !== 5 ||
      p.sla_max_duration_seconds != null ||
      p.bypass_concurrency
    );
  };

  useEffect(() => {
    if (selectedJob) {
      const nextScheduleMode: FormScheduleMode =
        selectedJob.depends_on && selectedJob.depends_on.length > 0 && selectedJob.schedule?.mode === "immediate"
          ? "dependency"
          : ((selectedJob.schedule?.mode ?? "immediate") as FormScheduleMode);
      setFormScheduleMode(nextScheduleMode);
      const nextPayload: JobPayload = {
        name: selectedJob.name,
        user: selectedJob.user || "default",
        affinity: { ...createDefaultPayload().affinity, ...selectedJob.affinity },
        executor: normalizeExecutor(selectedJob.executor),
        retries: selectedJob.retries,
        timeout: selectedJob.timeout,
        bypass_concurrency: selectedJob.bypass_concurrency ?? false,
        priority: (selectedJob as any).priority ?? 5,
        source: selectedJob.source ?? null,
        schedule: { ...createDefaultPayload().schedule, ...(selectedJob.schedule ?? {}) },
        completion: { ...createDefaultPayload().completion, ...(selectedJob.completion ?? {}) },
        tags: selectedJob.tags ?? [],
        depends_on: selectedJob.depends_on ?? [],
        retry_count: selectedJob.max_retries ?? 0,
        max_retries: selectedJob.max_retries ?? 0,
        retry_delay_seconds: selectedJob.retry_delay_seconds ?? 0,
        on_failure_webhooks: selectedJob.on_failure_webhooks ?? [],
        on_failure_email_to: selectedJob.on_failure_email_to ?? [],
        on_failure_email_credential_ref: selectedJob.on_failure_email_credential_ref ?? "",
        sla_max_duration_seconds: selectedJob.sla_max_duration_seconds ?? null,
      };
      setPayload(nextPayload);
      setNotifyWebhookEnabled((selectedJob.on_failure_webhooks ?? []).length > 0);
      setNotifyEmailEnabled(
        (selectedJob.on_failure_email_to ?? []).length > 0 || Boolean(selectedJob.on_failure_email_credential_ref),
      );
      setShowAdvanced(hasNonDefaultAdvanced(nextPayload));
    } else if (templatePayload) {
      const nextPayload: JobPayload = {
        ...createDefaultPayload(),
        ...templatePayload,
        affinity: { ...createDefaultPayload().affinity, ...(templatePayload.affinity ?? {}) },
        schedule: { ...createDefaultPayload().schedule, ...(templatePayload.schedule ?? {}) },
        completion: { ...createDefaultPayload().completion, ...(templatePayload.completion ?? {}) },
        executor: normalizeExecutor((templatePayload.executor ?? createDefaultPayload().executor) as JobDefinition["executor"]),
        depends_on: templatePayload.depends_on ?? [],
        on_failure_webhooks: templatePayload.on_failure_webhooks ?? [],
        on_failure_email_to: templatePayload.on_failure_email_to ?? [],
        on_failure_email_credential_ref: templatePayload.on_failure_email_credential_ref ?? "",
      };
      const mode: FormScheduleMode =
        (nextPayload.depends_on?.length ?? 0) > 0 && nextPayload.schedule.mode === "immediate"
          ? "dependency"
          : (nextPayload.schedule.mode as FormScheduleMode);
      setFormScheduleMode(mode);
      setPayload(nextPayload);
      setNotifyWebhookEnabled((nextPayload.on_failure_webhooks ?? []).length > 0);
      setNotifyEmailEnabled((nextPayload.on_failure_email_to ?? []).length > 0 || !!nextPayload.on_failure_email_credential_ref);
      if (hasNonDefaultAdvanced(nextPayload)) setShowAdvanced(true);
    } else {
      setFormScheduleMode("immediate");
      setPayload(createDefaultPayload());
      setNotifyWebhookEnabled(false);
      setNotifyEmailEnabled(false);
      setShowAdvanced(false);
    }
    setImportError(undefined);
    setLastValidation(undefined);
    userModifiedFields.clear();
  }, [selectedJob, templatePayload]);

  const executor = payload.executor;
  const executorType = executor.type;
  const schedule = payload.schedule;
  const pythonEnv =
    executor.type === "python"
      ? { ...createDefaultPythonEnvironment(), ...(executor.environment as PythonEnvironment | undefined) }
      : null;

  const updatePayload = (field: keyof JobPayload, value: any) => {
    userModifiedFields.add(field);
    setPayload((prev) => ({ ...prev, [field]: value }));
  };

  const updateExecutor = (update: Record<string, unknown>) => {
    setPayload((prev) => {
      const nextExecutor = { ...prev.executor, ...update } as JobPayload["executor"];
      return { ...prev, executor: nextExecutor };
    });
  };

  /** Change executor type with smart defaults for timeout & OS. */
  const handleExecutorTypeChange = (nextType: string) => {
    const defaults: Record<string, any> = {
      python: createDefaultPythonExecutor(),
      shell: { type: "shell", script: "echo 'hello world'", shell: "bash" },
      sql: { type: "sql", dialect: "postgres", query: "SELECT 1;", connection_uri: "", database: "" },
      external: { type: "external", command: "/usr/bin/env" },
      http: { type: "http", url: "", method: "GET", expected_status: [200], timeout_seconds: 30 },
      sensor: { type: "sensor", sensor_type: "http", target: "", method: "GET", headers: {}, expected_status: [200], poll_interval_seconds: 30, timeout_seconds: 3600 },
      batch: { type: "batch", script: "echo Hello", shell: "cmd" },
      powershell: { type: "powershell", script: "Write-Output 'Hello'", shell: "pwsh" },
    };
    const execDefaults = EXECUTOR_DEFAULTS[nextType];
    setPayload((prev) => {
      const nextPayload = { ...prev, executor: { ...prev.executor, ...defaults[nextType] } as JobPayload["executor"] };
      if (execDefaults && !userModifiedFields.has("timeout")) {
        nextPayload.timeout = execDefaults.timeout;
      }
      if (execDefaults && !userModifiedFields.has("affinity")) {
        nextPayload.affinity = { ...prev.affinity, os: execDefaults.os.length ? execDefaults.os : prev.affinity.os };
      }
      return nextPayload;
    });
  };

  const updateSchedule = (update: Record<string, unknown>) => {
    setPayload((prev) => ({ ...prev, schedule: { ...prev.schedule, ...update } }));
  };

  const updateCompletion = (update: Record<string, unknown>) => {
    setPayload((prev) => ({ ...prev, completion: { ...prev.completion, ...update } }));
  };

  const updateSource = (update: Partial<SourceConfig> | null) => {
    setPayload((prev) => {
      if (update === null) return { ...prev, source: null };
      return { ...prev, source: { ...(prev.source ?? { url: "", ref: "main" }), ...update } };
    });
  };

  const updatePythonEnv = (update: Partial<PythonEnvironment>) => {
    if (executor.type !== "python") return;
    const merged = {
      ...createDefaultPythonEnvironment(),
      ...(executor.environment as PythonEnvironment | undefined),
      ...update,
    };
    updateExecutor({ environment: merged });
  };

  const updateAffinity = (key: keyof typeof defaultAffinity, value: string[]) => {
    userModifiedFields.add("affinity");
    updatePayload("affinity", { ...payload.affinity, [key]: value });
  };

  const toInputValue = (iso?: string | null) => {
    if (!iso) return "";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    const local = new Date(d.getTime() - d.getTimezoneOffset() * 60_000);
    return local.toISOString().slice(0, 16);
  };
  const fromInputValue = (value: string) => (value ? new Date(value).toISOString() : null);

  const buildSubmissionPayload = (source: JobPayload): JobPayload => {
    return {
      ...source,
      user: source.user?.trim() || "default",
      source: source.source?.url?.trim() ? source.source : null,
      schedule: {
        ...source.schedule,
        mode: formScheduleMode === "dependency" ? "immediate" : source.schedule.mode,
      },
      depends_on: formScheduleMode === "dependency" ? (source.depends_on ?? []) : [],
      on_failure_email_credential_ref: (source.on_failure_email_credential_ref ?? "").trim(),
      on_failure_webhooks: notifyWebhookEnabled ? (source.on_failure_webhooks ?? []) : [],
      on_failure_email_to: notifyEmailEnabled ? (source.on_failure_email_to ?? []) : [],
      // executor_types intentionally omitted -- backend auto-derives from executor.type
      affinity: {
        ...source.affinity,
      },
    };
  };

  const handleValidateOnly = async () => {
    const result = await onValidate(buildSubmissionPayload(payload));
    setLastValidation(result);
    return result;
  };

  const handleValidateThenSubmit = async () => {
    const normalized = buildSubmissionPayload(payload);
    if (formScheduleMode === "dependency" && (normalized.depends_on?.length ?? 0) === 0) {
      setImportError("Dependency mode requires at least one prerequisite job.");
      return;
    }
    setImportError(undefined);
    const validation = await onValidate(normalized);
    setLastValidation(validation);
    if (!validation?.valid) return;
    await onSubmit(normalized);
  };

  const handleScheduleModeChange = (mode: FormScheduleMode) => {
    setImportError(undefined);
    setLastValidation(undefined);
    setFormScheduleMode(mode);
    if (mode === "dependency") {
      updateSchedule({ mode: "immediate", enabled: true, cron: "", interval_seconds: null, start_at: null, end_at: null, next_run_at: null });
      return;
    }
    updateSchedule({ mode, next_run_at: null });
    if ((payload.depends_on ?? []).length > 0) updatePayload("depends_on", []);
  };

  const handleExportJson = () => {
    const toExport = buildSubmissionPayload(payload);
    const blob = new Blob([JSON.stringify(toExport, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${(payload.name || "hydra-job").replace(/\s+/g, "-").toLowerCase()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleImportJsonFile = (file: File) => {
    file
      .text()
      .then((raw) => {
        const imported = JSON.parse(raw) as Partial<JobPayload>;
        if (!imported || typeof imported !== "object" || !imported.executor) {
          throw new Error("Invalid job JSON format");
        }
        const nextPayload: JobPayload = {
          ...createDefaultPayload(),
          ...imported,
          affinity: { ...createDefaultPayload().affinity, ...(imported.affinity ?? {}) },
          schedule: { ...createDefaultPayload().schedule, ...(imported.schedule ?? {}) },
          completion: { ...createDefaultPayload().completion, ...(imported.completion ?? {}) },
          executor: normalizeExecutor(imported.executor as JobDefinition["executor"]),
          depends_on: imported.depends_on ?? [],
          on_failure_webhooks: imported.on_failure_webhooks ?? [],
          on_failure_email_to: imported.on_failure_email_to ?? [],
          on_failure_email_credential_ref: imported.on_failure_email_credential_ref ?? "",
        };
        setPayload(nextPayload);
        setNotifyWebhookEnabled((nextPayload.on_failure_webhooks ?? []).length > 0);
        setNotifyEmailEnabled(
          (nextPayload.on_failure_email_to ?? []).length > 0 || Boolean(nextPayload.on_failure_email_credential_ref),
        );
        const importedMode: FormScheduleMode =
          (nextPayload.depends_on?.length ?? 0) > 0 && nextPayload.schedule.mode === "immediate"
            ? "dependency"
            : (nextPayload.schedule.mode as FormScheduleMode);
        setFormScheduleMode(importedMode);
        setImportError(undefined);
        if (hasNonDefaultAdvanced(nextPayload)) setShowAdvanced(true);
      })
      .catch((err: Error) => {
        setImportError(err.message || "Failed to import JSON");
      });
  };

  // ── Executor-type-specific form fields ────────────────────────────────
  const executorTypeSelect = (
    <Form.Item label="Executor Type" required>
      <Select
        value={executorType}
        onChange={handleExecutorTypeChange}
        options={[
          { label: "Shell", value: "shell" },
          { label: "Python", value: "python" },
          { label: "SQL / Database", value: "sql" },
          { label: "External Binary", value: "external" },
          { label: "HTTP Request", value: "http" },
          { label: "Sensor / Poller", value: "sensor" },
          { label: "Batch (Windows cmd)", value: "batch" },
          { label: "PowerShell", value: "powershell" },
        ]}
      />
    </Form.Item>
  );

  const renderExecutorFields = () => (
    <>
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

      {executor.type === "shell" && (
        <>
          <Row gutter={16}>
            <Col xs={24} md={12}>
              <Form.Item label="Shell">
                <Select
                  value={executor.shell ?? "bash"}
                  onChange={(val) => updateExecutor({ shell: val })}
                  options={[
                    { label: "bash", value: "bash" },
                    { label: "sh", value: "sh" },
                    { label: "zsh", value: "zsh" },
                    { label: "pwsh", value: "pwsh" },
                    { label: "powershell", value: "powershell" },
                    { label: "cmd", value: "cmd" },
                  ]}
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
          <Form.Item label="Command">
            <Input.TextArea
              value={executor.script ?? ""}
              onChange={(e) => updateExecutor({ script: e.target.value })}
              autoSize={{ minRows: 2, maxRows: 6 }}
              placeholder="python -m pip list"
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

      {(executor.type === "batch" || executor.type === "powershell") && (
        <>
          <Row gutter={16}>
            <Col xs={24} md={12}>
              <Form.Item label="Shell">
                <Select
                  value={(executor as any).shell ?? (executor.type === "batch" ? "cmd" : "pwsh")}
                  onChange={(val) => updateExecutor({ shell: val })}
                  options={
                    executor.type === "batch"
                      ? [{ label: "cmd", value: "cmd" }]
                      : [
                          { label: "pwsh", value: "pwsh" },
                          { label: "powershell", value: "powershell" },
                        ]
                  }
                />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item label="Working Directory">
                <Input
                  value={(executor as any).workdir ?? ""}
                  onChange={(e) => updateExecutor({ workdir: e.target.value || null })}
                  placeholder="C:\\jobs"
                />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item label="Script">
            <Input.TextArea
              value={(executor as any).script ?? ""}
              onChange={(e) => updateExecutor({ script: e.target.value })}
              autoSize={{ minRows: 4, maxRows: 10 }}
              placeholder={executor.type === "batch" ? "echo Hello from cmd" : "Write-Output 'Hello from PowerShell'"}
            />
          </Form.Item>
        </>
      )}

      {executor.type === "http" && (
        <>
          <Row gutter={16}>
            <Col xs={24} md={16}>
              <Form.Item label="URL" required>
                <Input
                  value={(executor as any).url ?? ""}
                  onChange={(e) => updateExecutor({ url: e.target.value })}
                  placeholder="https://api.example.com/endpoint"
                />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item label="Method">
                <Select
                  value={(executor as any).method ?? "GET"}
                  onChange={(val) => updateExecutor({ method: val })}
                  options={[
                    { label: "GET", value: "GET" },
                    { label: "POST", value: "POST" },
                    { label: "PUT", value: "PUT" },
                    { label: "PATCH", value: "PATCH" },
                    { label: "DELETE", value: "DELETE" },
                  ]}
                />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col xs={24} md={12}>
              <Form.Item label="Expected Status Code">
                <InputNumber
                  min={100}
                  max={599}
                  style={{ width: "100%" }}
                  value={((executor as any).expected_status as number[])?.[0] ?? 200}
                  onChange={(val) => updateExecutor({ expected_status: [val ?? 200] })}
                />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item label="Timeout (seconds)">
                <InputNumber
                  min={1}
                  style={{ width: "100%" }}
                  value={(executor as any).timeout_seconds ?? 30}
                  onChange={(val) => updateExecutor({ timeout_seconds: val ?? 30 })}
                />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item label="Request Body (JSON)">
            <Input.TextArea
              value={(executor as any).body ?? ""}
              onChange={(e) => updateExecutor({ body: e.target.value })}
              autoSize={{ minRows: 3 }}
              placeholder='{"key": "value"}'
            />
          </Form.Item>
          <Form.Item label="Headers (KEY=VALUE per line)">
            <Input.TextArea
              value={
                (executor as any).headers
                  ? Object.entries((executor as any).headers as Record<string, string>)
                      .map(([k, v]) => `${k}=${v}`)
                      .join("\n")
                  : ""
              }
              onChange={(e) => {
                const headers: Record<string, string> = {};
                e.target.value.split("\n").forEach((line) => {
                  const [k, ...rest] = line.split("=");
                  if (k && rest.length) headers[k.trim()] = rest.join("=").trim();
                });
                updateExecutor({ headers });
              }}
              autoSize
              placeholder="Authorization=Bearer token"
            />
          </Form.Item>
        </>
      )}

      {executor.type === "sensor" && (
        <>
          <Row gutter={16}>
            <Col xs={24} md={8}>
              <Form.Item label="Sensor Type">
                <Select
                  value={(executor as any).sensor_type ?? "http"}
                  onChange={(val) => updateExecutor({ sensor_type: val })}
                  options={[
                    { label: "HTTP", value: "http" },
                    { label: "SQL", value: "sql" },
                  ]}
                />
              </Form.Item>
            </Col>
            <Col xs={24} md={16}>
              <Form.Item
                label={(executor as any).sensor_type === "sql" ? "Connection URI" : "Target URL"}
                required
              >
                <Input
                  value={(executor as any).target ?? ""}
                  onChange={(e) => updateExecutor({ target: e.target.value })}
                  placeholder={
                    (executor as any).sensor_type === "sql"
                      ? "postgresql://user:pass@host:5432/db"
                      : "https://api.example.com/health"
                  }
                />
              </Form.Item>
            </Col>
          </Row>
          {(executor as any).sensor_type !== "sql" && (
            <Row gutter={16}>
              <Col xs={24} md={8}>
                <Form.Item label="Method">
                  <Select
                    value={(executor as any).method ?? "GET"}
                    onChange={(val) => updateExecutor({ method: val })}
                    options={[
                      { label: "GET", value: "GET" },
                      { label: "POST", value: "POST" },
                      { label: "PUT", value: "PUT" },
                      { label: "PATCH", value: "PATCH" },
                      { label: "DELETE", value: "DELETE" },
                    ]}
                  />
                </Form.Item>
              </Col>
              <Col xs={24} md={8}>
                <Form.Item label="Expected Status">
                  <InputNumber
                    min={100}
                    max={599}
                    style={{ width: "100%" }}
                    value={((executor as any).expected_status as number[])?.[0] ?? 200}
                    onChange={(val) => updateExecutor({ expected_status: [val ?? 200] })}
                  />
                </Form.Item>
              </Col>
            </Row>
          )}
          <Row gutter={16}>
            <Col xs={24} md={12}>
              <Form.Item label="Poll Interval (seconds)">
                <InputNumber
                  min={1}
                  style={{ width: "100%" }}
                  value={(executor as any).poll_interval_seconds ?? 30}
                  onChange={(val) => updateExecutor({ poll_interval_seconds: val ?? 30 })}
                />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item label="Timeout (seconds)">
                <InputNumber
                  min={1}
                  style={{ width: "100%" }}
                  value={(executor as any).timeout_seconds ?? 3600}
                  onChange={(val) => updateExecutor({ timeout_seconds: val ?? 3600 })}
                />
              </Form.Item>
            </Col>
          </Row>
        </>
      )}

      {executor.type === "sql" && (
        <>
          <Row gutter={16}>
            <Col xs={24} md={8}>
              <Form.Item label="Dialect">
                <Select
                  value={(executor as any).dialect ?? "postgres"}
                  onChange={(val) => updateExecutor({ dialect: val })}
                  options={[
                    { label: "PostgreSQL", value: "postgres" },
                    { label: "MySQL", value: "mysql" },
                    { label: "SQL Server", value: "mssql" },
                    { label: "Oracle", value: "oracle" },
                    { label: "MongoDB", value: "mongodb" },
                  ]}
                />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item label="Database">
                <Input
                  value={(executor as any).database ?? ""}
                  onChange={(e) => updateExecutor({ database: e.target.value })}
                  placeholder="mydb"
                />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item label="Credential Reference">
                <Input
                  value={(executor as any).credential_ref ?? ""}
                  onChange={(e) => updateExecutor({ credential_ref: e.target.value || null })}
                  placeholder="stored credential name (optional)"
                />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item label="Connection URI">
            <Input
              value={(executor as any).connection_uri ?? ""}
              onChange={(e) => updateExecutor({ connection_uri: e.target.value })}
              placeholder="postgresql://user:pass@host:5432/db"
            />
          </Form.Item>
          <Form.Item label="SQL Query">
            <Input.TextArea
              value={(executor as any).query ?? ""}
              onChange={(e) => updateExecutor({ query: e.target.value })}
              autoSize={{ minRows: 8 }}
              placeholder="SELECT * FROM table LIMIT 10;"
            />
          </Form.Item>
          <Alert
            type="info"
            showIcon
            message="Workers require sqlalchemy (relational) or pymongo (MongoDB). Credentials can be stored via Admin > Credentials."
            style={{ marginBottom: 12 }}
          />
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

      <Form.Item label="Arguments">
        <Input
          value={(executor as any).args?.join(" ") ?? ""}
          onChange={(e) => updateExecutor({ args: e.target.value.split(" ").filter(Boolean) })}
          placeholder="--flag value"
        />
      </Form.Item>
    </>
  );

  // ── Schedule fields (inline in Step 1) ────────────────────────────────
  const renderScheduleFields = () => (
    <>
      <Row gutter={16} align="middle">
        <Col xs={24} md={8}>
          <Form.Item label="Schedule">
            <Select
              value={formScheduleMode}
              onChange={(mode) => handleScheduleModeChange(mode as FormScheduleMode)}
              options={[
                { label: "Manual / Immediate", value: "immediate" },
                { label: "Interval", value: "interval" },
                { label: "Cron", value: "cron" },
                { label: "Dependency", value: "dependency" },
              ]}
            />
          </Form.Item>
        </Col>
        {(formScheduleMode === "cron" || formScheduleMode === "interval") && (
          <Col xs={24} md={8}>
            <Form.Item label="Enabled">
              <Switch checked={schedule.enabled} onChange={(checked) => updateSchedule({ enabled: checked })} />
            </Form.Item>
          </Col>
        )}
        <Col xs={24} md={8}>
          <Typography.Text type="secondary">
            {!schedule.enabled
              ? "Disabled"
              : schedule.next_run_at
                ? `Next: ${new Date(schedule.next_run_at).toLocaleString()}`
                : formScheduleMode === "immediate" || formScheduleMode === "dependency"
                  ? "Runs when triggered"
                  : "Pending validation"}
          </Typography.Text>
        </Col>
      </Row>

      {formScheduleMode === "dependency" && (
        <Form.Item label="Depends On" tooltip="This job will run when all selected jobs finish successfully.">
          <Select
            mode="multiple"
            style={{ width: "100%" }}
            placeholder="Select prerequisite jobs..."
            value={payload.depends_on ?? []}
            onChange={(value) => updatePayload("depends_on", value)}
            options={allJobs
              .filter((j) => j._id !== selectedJob?._id)
              .map((j) => ({ label: `${j.name} (${j._id.slice(0, 8)})`, value: j._id }))}
            filterOption={(input, option) =>
              ((option?.label as string) ?? "").toLowerCase().includes(input.toLowerCase())
            }
          />
        </Form.Item>
      )}

      {formScheduleMode === "interval" && (
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

      {formScheduleMode === "cron" && (
        <>
          <Row gutter={16}>
            <Col xs={24} md={12}>
              <Form.Item label="Preset">
                <Select
                  placeholder="Choose a preset or type below…"
                  allowClear
                  value={[
                    "*/1 * * * *", "*/5 * * * *", "*/15 * * * *", "*/30 * * * *",
                    "0 * * * *", "0 0 * * *", "0 6 * * *", "0 0 * * 0", "0 0 1 * *",
                  ].includes(schedule.cron ?? "") ? schedule.cron : undefined}
                  onChange={(val: string | undefined) => {
                    setLastValidation(undefined);
                    updateSchedule({ cron: val ?? "" });
                  }}
                  options={[
                    { label: "Every minute  (*/1 * * * *)", value: "*/1 * * * *" },
                    { label: "Every 5 minutes  (*/5 * * * *)", value: "*/5 * * * *" },
                    { label: "Every 15 minutes  (*/15 * * * *)", value: "*/15 * * * *" },
                    { label: "Every 30 minutes  (*/30 * * * *)", value: "*/30 * * * *" },
                    { label: "Hourly  (0 * * * *)", value: "0 * * * *" },
                    { label: "Daily at midnight  (0 0 * * *)", value: "0 0 * * *" },
                    { label: "Daily at 6 AM  (0 6 * * *)", value: "0 6 * * *" },
                    { label: "Weekly (Sunday midnight)  (0 0 * * 0)", value: "0 0 * * 0" },
                    { label: "Monthly (1st at midnight)  (0 0 1 * *)", value: "0 0 1 * *" },
                  ]}
                />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item label="Timezone">
                <Select
                  showSearch
                  value={schedule.timezone ?? "UTC"}
                  onChange={(val) => updateSchedule({ timezone: val })}
                  options={(
                    typeof Intl !== "undefined" && (Intl as any).supportedValuesOf
                      ? (Intl as any).supportedValuesOf("timeZone")
                      : ["UTC", "America/New_York", "America/Chicago", "America/Los_Angeles", "Europe/London", "Europe/Paris", "Asia/Tokyo", "Asia/Shanghai", "Australia/Sydney"]
                  ).map((tz: string) => ({ label: tz, value: tz }))}
                  filterOption={(input, option) =>
                    (option?.label as string ?? "").toLowerCase().includes(input.toLowerCase())
                  }
                />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={24}>
              <Form.Item label="Cron Expression">
                <Input
                  value={schedule.cron ?? ""}
                  onChange={(e) => {
                    setLastValidation(undefined);
                    updateSchedule({ cron: e.target.value });
                  }}
                  placeholder="*/5 * * * *"
                />
              </Form.Item>
              <Space direction="vertical" size={4} style={{ width: "100%" }}>
                <Typography.Text type="secondary">
                  Standard 5-field cron: minute hour day-of-month month day-of-week.{" "}
                  <Typography.Link href="https://crontab.guru" target="_blank" rel="noopener noreferrer">
                    crontab.guru ↗
                  </Typography.Link>
                </Typography.Text>
                <Button size="small" onClick={handleValidateOnly} loading={validating}>
                  Preview Cron
                </Button>
                {lastValidation?.next_run_at && (
                  <Typography.Text type="secondary">
                    Next run: {new Date(lastValidation.next_run_at).toLocaleString()} (local)
                  </Typography.Text>
                )}
                {lastValidation && !lastValidation.valid && (
                  <Alert
                    type="error"
                    showIcon
                    message={
                      lastValidation.errors.find((e) => e.toLowerCase().includes("cron")) ??
                      "Cron expression is invalid."
                    }
                  />
                )}
              </Space>
            </Col>
          </Row>
        </>
      )}

      {(formScheduleMode === "interval" || formScheduleMode === "cron") && (
        <Row gutter={16} style={{ marginTop: 8 }}>
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

  // ── Advanced panel: auto-opens when editing jobs with non-default values ──
  const advancedActiveKeys = useMemo(() => {
    if (!showAdvanced) return [];
    const keys: string[] = [];
    const p = payload;
    if (
      (p.affinity.hostnames?.length ?? 0) > 0 ||
      (p.affinity.subnets?.length ?? 0) > 0 ||
      (p.affinity.deployment_types?.length ?? 0) > 0 ||
      (p.affinity.allowed_users?.length ?? 0) > 0 ||
      (p.affinity.tags?.length ?? 0) > 0
    )
      keys.push("placement");
    if (
      p.completion.exit_codes.length !== 1 ||
      p.completion.exit_codes[0] !== 0 ||
      p.completion.stdout_contains.length > 0 ||
      p.completion.stdout_not_contains.length > 0
    )
      keys.push("completion");
    if ((p.on_failure_webhooks?.length ?? 0) > 0 || (p.on_failure_email_to?.length ?? 0) > 0) keys.push("notifications");
    if ((p.executor as any).impersonate_user || (p.executor as any).kerberos?.principal) keys.push("auth");
    if (p.source) keys.push("source");
    if ((p.retries ?? 0) > 0 || (p.max_retries ?? 0) > 0) keys.push("retry-advanced");
    if (p.priority !== 5 || p.sla_max_duration_seconds != null || p.bypass_concurrency) keys.push("misc");
    return keys;
  }, [showAdvanced, payload]);

  return (
    <Form layout="vertical" onFinish={handleValidateThenSubmit} size="small">
      <input
        ref={importInputRef}
        type="file"
        accept=".json,application/json"
        style={{ display: "none" }}
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) handleImportJsonFile(file);
          e.currentTarget.value = "";
        }}
      />

      {/* ── Magic Job Generator ── */}
      {!selectedJob && (
        <Alert
          message="Magic Job Generator"
          description={
            <Space.Compact style={{ width: "100%" }}>
              <ProviderSelect value={provider} onChange={setProvider} style={{ width: 100 }} />
              <Input
                placeholder="Describe your job (e.g., 'Run a backup script every Sunday at 2am')"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                onPressEnter={handleGenerate}
              />
              <Button type="primary" loading={generating} onClick={handleGenerate}>
                Generate
              </Button>
            </Space.Compact>
          }
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
        />
      )}

      {importError && <Alert type="error" showIcon message={importError} style={{ marginBottom: 12 }} />}

      <Space wrap style={{ marginBottom: 8 }}>
        <Button onClick={handleExportJson}>Export JSON</Button>
        <Button onClick={() => importInputRef.current?.click()}>Import JSON</Button>
      </Space>

      {/* ── Step 1: Define Job ── */}
      <Divider orientation="left" plain>
        Job Definition
      </Divider>

      <Row gutter={16}>
        <Col xs={24} md={12}>
          <Form.Item label="Name" required>
            <Input value={payload.name} onChange={(e) => updatePayload("name", e.target.value)} placeholder="batch-import" />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item label="Tags">
            <Select
              mode="tags"
              style={{ width: "100%" }}
              placeholder="production, data-import, critical"
              value={payload.tags ?? []}
              onChange={(value) => updatePayload("tags", value)}
            />
          </Form.Item>
        </Col>
      </Row>

      <Row gutter={16}>
        <Col xs={24} md={12}>
          {executorTypeSelect}
        </Col>
        <Col xs={24} md={6}>
          <Form.Item label="Timeout (seconds)">
            <InputNumber
              min={0}
              style={{ width: "100%" }}
              value={payload.timeout}
              onChange={(value) => updatePayload("timeout", Number(value))}
            />
          </Form.Item>
        </Col>
        <Col xs={24} md={6}>
          <Form.Item label="Retries" tooltip="Number of times to retry on failure">
            <InputNumber
              min={0}
              style={{ width: "100%" }}
              value={payload.retry_count ?? 0}
              onChange={(value) => updatePayload("retry_count", Number(value))}
            />
          </Form.Item>
        </Col>
      </Row>

      {renderExecutorFields()}

      <Divider orientation="left" plain>
        Schedule
      </Divider>
      {renderScheduleFields()}

      {/* ── Step 2: Advanced (collapsed by default) ── */}
      <Divider orientation="left" plain>
        <Space>
          Advanced Settings
          <Switch
            size="small"
            checked={showAdvanced}
            onChange={setShowAdvanced}
          />
        </Space>
      </Divider>

      {showAdvanced && (
        <Space direction="vertical" size={8} style={{ width: "100%" }}>
          <PlacementSection payload={payload} updateAffinity={updateAffinity} workerHints={workerHints} />
          <CompletionSection completion={payload.completion} updateCompletion={updateCompletion} />
          <NotificationsSection
            payload={payload}
            updatePayload={updatePayload}
            notifyWebhookEnabled={notifyWebhookEnabled}
            setNotifyWebhookEnabled={setNotifyWebhookEnabled}
            notifyEmailEnabled={notifyEmailEnabled}
            setNotifyEmailEnabled={setNotifyEmailEnabled}
          />
          <AuthSection executor={executor} updateExecutor={updateExecutor} />
          <SourceSection source={payload.source} updateSource={updateSource} />
          <RetryAdvancedSection payload={payload} updatePayload={updatePayload} />
          <MiscSection payload={payload} updatePayload={updatePayload} />
        </Space>
      )}

      {/* ── Action buttons ── */}
      <Divider style={{ margin: "12px 0" }} />
      <Space wrap>
        <Button type="primary" htmlType="submit" loading={submitting || validating}>
          {selectedJob ? "Validate & Update" : "Validate & Submit"}
        </Button>
        <Button onClick={handleValidateOnly} loading={validating}>
          Validate
        </Button>
        {!selectedJob && (
          <Button
            onClick={() => {
              const normalized = buildSubmissionPayload(payload);
              onAdhocRun(normalized);
            }}
            disabled={submitting}
            type="dashed"
          >
            Run Non-Persistent
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
        <Button
          onClick={() => {
            setPayload(createDefaultPayload());
            setFormScheduleMode("immediate");
            setImportError(undefined);
            setShowAdvanced(false);
            (onCancel ?? onReset)();
          }}
        >
          Cancel
        </Button>
      </Space>
      {!selectedJob && (
        <Typography.Text type="secondary" style={{ display: "block", marginTop: 4 }}>
          Non-Persistent runs once without saving. Submit saves the job definition.
        </Typography.Text>
      )}
      {statusMessage && <Typography.Paragraph style={{ marginTop: "0.5rem" }}>{statusMessage}</Typography.Paragraph>}
    </Form>
  );
}
