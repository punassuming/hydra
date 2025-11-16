import { useEffect, useMemo, useState } from "react";
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

  const handleSubmit = (evt: React.FormEvent) => {
    evt.preventDefault();
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
    <form className="panel" onSubmit={handleSubmit}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2>{selectedJob ? "Update Job" : "Create Job"}</h2>
        {selectedJob && (
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <button type="button" onClick={onManualRun} style={{ backgroundColor: "#0d9488" }}>
              Run Now
            </button>
            <button type="button" onClick={onReset} style={{ backgroundColor: "#475569" }}>
              New Job
            </button>
          </div>
        )}
      </div>
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
        <label>
          Name
          <input value={payload.name} onChange={(e) => updatePayload("name", e.target.value)} required />
        </label>
        <label>
          User
          <input value={payload.user} onChange={(e) => updatePayload("user", e.target.value)} required />
        </label>
        <label>
          Timeout (seconds)
          <input type="number" min={0} value={payload.timeout} onChange={(e) => updatePayload("timeout", Number(e.target.value))} />
        </label>
        <label>
          Retries
          <input type="number" min={0} value={payload.retries} onChange={(e) => updatePayload("retries", Number(e.target.value))} />
        </label>
      </div>
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))" }}>
        <label>
          Target OS (comma separated)
          <input value={affinityDisplay.os} onChange={(e) => setAffinity("os", e.target.value)} />
        </label>
        <label>
          Tags
          <input value={affinityDisplay.tags} onChange={(e) => setAffinity("tags", e.target.value)} />
        </label>
        <label>
          Allowed Users
          <input value={affinityDisplay.allowed_users} onChange={(e) => setAffinity("allowed_users", e.target.value)} />
        </label>
      </div>

      <div style={{ marginTop: "1rem" }}>
        <h3>Schedule</h3>
        <label>
          Mode
          <select
            value={schedule.mode}
            onChange={(e) => {
              const mode = e.target.value as JobPayload["schedule"]["mode"];
              updateSchedule({ mode, next_run_at: null });
            }}
          >
            <option value="immediate">Immediate</option>
            <option value="interval">Interval</option>
            <option value="cron">Cron</option>
          </select>
        </label>
        <label>
          Enabled
          <input type="checkbox" checked={schedule.enabled} onChange={(e) => updateSchedule({ enabled: e.target.checked })} />
        </label>
        {schedule.mode === "interval" && (
          <label>
            Interval (seconds)
            <input
              type="number"
              min={1}
              value={schedule.interval_seconds ?? 300}
              onChange={(e) => updateSchedule({ interval_seconds: Number(e.target.value) })}
            />
          </label>
        )}
        {schedule.mode === "cron" && (
          <label>
            Cron Expression
            <input value={schedule.cron ?? ""} onChange={(e) => updateSchedule({ cron: e.target.value })} placeholder="*/5 * * * *" />
          </label>
        )}
        {(schedule.mode === "interval" || schedule.mode === "cron") && (
          <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))" }}>
            <label>
              Start At
              <input type="datetime-local" value={toInputValue(schedule.start_at)} onChange={(e) => updateSchedule({ start_at: fromInputValue(e.target.value) })} />
            </label>
            <label>
              End At
              <input type="datetime-local" value={toInputValue(schedule.end_at)} onChange={(e) => updateSchedule({ end_at: fromInputValue(e.target.value) })} />
            </label>
          </div>
        )}
        <p style={{ fontSize: "0.85rem", color: "#475569" }}>
          Next run: {!schedule.enabled ? "Disabled" : schedule.next_run_at ? new Date(schedule.next_run_at).toLocaleString() : schedule.mode === "immediate" ? "Immediately" : "pending"}
        </p>
      </div>

      <div style={{ marginTop: "1rem" }}>
        <h3>Completion Criteria</h3>
        <label>
          Exit Codes (comma separated)
          <input
            value={completion.exit_codes.join(", ")}
            onChange={(e) => {
              const values = parseList(e.target.value)
                .map((c) => Number(c))
                .filter((n) => !Number.isNaN(n));
              updateCompletion({ exit_codes: values.length ? values : [] });
            }}
          />
        </label>
        <label>
          Stdout must contain (one per line)
          <textarea value={completion.stdout_contains.join("\n")} onChange={(e) => setCompletionList("stdout_contains", e.target.value)} />
        </label>
        <label>
          Stdout must NOT contain
          <textarea value={completion.stdout_not_contains.join("\n")} onChange={(e) => setCompletionList("stdout_not_contains", e.target.value)} />
        </label>
        <label>
          Stderr must contain (one per line)
          <textarea value={completion.stderr_contains.join("\n")} onChange={(e) => setCompletionList("stderr_contains", e.target.value)} />
        </label>
        <label>
          Stderr must NOT contain
          <textarea value={completion.stderr_not_contains.join("\n")} onChange={(e) => setCompletionList("stderr_not_contains", e.target.value)} />
        </label>
      </div>
      <div style={{ marginTop: "0.75rem" }}>
        <label>
          Executor Type
          <select
            value={executorType}
            onChange={(e) => {
              const nextType = e.target.value as JobPayload["executor"]["type"];
              const defaults: Record<string, any> = {
                python: createDefaultPythonExecutor(),
                shell: { type: "shell", script: "echo 'hello world'", shell: "bash" },
                batch: { type: "batch", script: "echo hello", shell: "cmd" },
                external: { type: "external", command: "/usr/bin/env" },
              };
              updateExecutor(defaults[nextType]);
            }}
          >
            <option value="shell">Shell</option>
            <option value="batch">Batch</option>
            <option value="python">Python</option>
            <option value="external">External Binary</option>
          </select>
        </label>
      </div>

      {executor.type === "python" && (
        <>
          <label>
            Interpreter
            <input value={executor.interpreter ?? "python3"} onChange={(e) => updateExecutor({ interpreter: e.target.value })} />
          </label>
          <label>
            Python Code
            <textarea value={executor.code ?? ""} onChange={(e) => updateExecutor({ code: e.target.value })} required />
          </label>
          {pythonEnv && (
            <div style={{ marginTop: "0.5rem" }}>
              <h3>Python Environment</h3>
              <label>
                Environment Type
                <select value={pythonEnv.type} onChange={(e) => updatePythonEnv({ type: e.target.value as PythonEnvironment["type"] })}>
                  <option value="system">System</option>
                  <option value="venv">Virtualenv</option>
                  <option value="uv">uv (isolated)</option>
                </select>
              </label>
              <label>
                Python Version
                <input
                  value={pythonEnv.python_version ?? ""}
                  onChange={(e) => updatePythonEnv({ python_version: e.target.value || null })}
                  placeholder="3.11 or python3.11"
                />
              </label>
              {pythonEnv.type === "venv" && (
                <label>
                  Virtualenv Path
                  <input
                    value={pythonEnv.venv_path ?? ""}
                    onChange={(e) => updatePythonEnv({ venv_path: e.target.value || null })}
                    placeholder="Existing venv path or leave blank"
                  />
                </label>
              )}
              <label>
                Requirements (one per line)
                <textarea
                  value={(pythonEnv.requirements ?? []).join("\n")}
                  onChange={(e) => updatePythonEnv({ requirements: parseList(e.target.value) })}
                  placeholder="requests==2.32.0"
                />
              </label>
              <label>
                Requirements File
                <input
                  value={pythonEnv.requirements_file ?? ""}
                  onChange={(e) => updatePythonEnv({ requirements_file: e.target.value || null })}
                  placeholder="/workspace/requirements.txt"
                />
              </label>
              {pythonEnv.type === "uv" && (
                <p style={{ fontSize: "0.85rem", color: "#475569" }}>Requires the uv CLI on the worker image.</p>
              )}
            </div>
          )}
        </>
      )}

      {(executor.type === "shell" || executor.type === "batch") && (
        <>
          <label>
            Shell
            <input value={executor.shell ?? (executor.type === "batch" ? "cmd" : "bash")} onChange={(e) => updateExecutor({ shell: e.target.value })} />
          </label>
          <label>
            Script
            <textarea value={executor.script ?? ""} onChange={(e) => updateExecutor({ script: e.target.value })} required />
          </label>
        </>
      )}

      {executor.type === "external" && (
        <label>
          Command / Binary Path
          <input value={executor.command ?? ""} onChange={(e) => updateExecutor({ command: e.target.value })} required />
        </label>
      )}

      <label>
        Arguments (space separated)
        <input
          value={(executor.args ?? []).join(" ")}
          onChange={(e) => updateExecutor({ args: e.target.value.split(" ").filter(Boolean) })}
          placeholder="--flag value"
        />
      </label>

      <label>
        Working Directory (optional)
        <input value={executor.workdir ?? ""} onChange={(e) => updateExecutor({ workdir: e.target.value || null })} placeholder="/opt/jobs" />
      </label>

      <label>
        Environment Variables (KEY=VALUE per line)
        <textarea
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
        />
      </label>

      <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", marginTop: "0.5rem" }}>
        <button type="submit" disabled={submitting}>
          {selectedJob ? "Update Job" : "Submit Job"}
        </button>
        <button type="button" onClick={handleValidate} disabled={validating} style={{ backgroundColor: "#0d9488" }}>
          Validate
        </button>
        {!selectedJob && (
          <button
            type="button"
            onClick={() => onAdhocRun(payload)}
            disabled={submitting}
            style={{ backgroundColor: "#6d28d9" }}
          >
            Run Adhoc
          </button>
        )}
        {statusMessage && <span style={{ fontSize: "0.85rem", color: "#0f766e" }}>{statusMessage}</span>}
      </div>
    </form>
  );
}
