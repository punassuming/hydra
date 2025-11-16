import { useEffect, useMemo, useState } from "react";
import { JobDefinition } from "../types";
import { JobPayload } from "../api/jobs";

const createDefaultPayload = (): JobPayload => ({
  name: "",
  user: "",
  affinity: { os: ["linux"], tags: [], allowed_users: [] },
  executor: { type: "shell", script: "echo 'hello world'", shell: "bash" },
  retries: 0,
  timeout: 30,
  schedule: "",
});

interface Props {
  selectedJob?: JobDefinition | null;
  onSubmit: (payload: JobPayload) => void;
  onValidate: (payload: JobPayload) => void;
  submitting: boolean;
  validating: boolean;
  statusMessage?: string;
  onReset: () => void;
}

export function JobForm({ selectedJob, onSubmit, onValidate, submitting, validating, statusMessage, onReset }: Props) {
  const [payload, setPayload] = useState<JobPayload>(() => createDefaultPayload());

  useEffect(() => {
    if (selectedJob) {
      setPayload({
        name: selectedJob.name,
        user: selectedJob.user,
        affinity: selectedJob.affinity,
        executor: selectedJob.executor,
        retries: selectedJob.retries,
        timeout: selectedJob.timeout,
        schedule: selectedJob.schedule ?? "",
      });
    } else {
      setPayload(createDefaultPayload());
    }
  }, [selectedJob]);

  const executor = payload.executor;
  const executorType = executor.type;

  const updatePayload = (field: keyof JobPayload, value: any) => {
    setPayload((prev) => ({ ...prev, [field]: value }));
  };

  const updateExecutor = (update: Record<string, unknown>) => {
    setPayload((prev) => ({ ...prev, executor: { ...prev.executor, ...update } as JobPayload["executor"] }));
  };

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
          <button type="button" onClick={onReset} style={{ backgroundColor: "#475569" }}>
            New Job
          </button>
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
          Schedule (cron)
          <input value={payload.schedule ?? ""} onChange={(e) => updatePayload("schedule", e.target.value)} placeholder="*/5 * * * *" />
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
      <div style={{ marginTop: "0.75rem" }}>
        <label>
          Executor Type
          <select
            value={executorType}
            onChange={(e) => {
              const nextType = e.target.value as JobPayload["executor"]["type"];
              const defaults: Record<string, any> = {
                python: { type: "python", code: "print('hello')", interpreter: "python3" },
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
        {statusMessage && <span style={{ fontSize: "0.85rem", color: "#0f766e" }}>{statusMessage}</span>}
      </div>
    </form>
  );
}
