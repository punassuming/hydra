import { useState } from "react";
import { Drawer, Space, Typography, Button, Tag, Divider, Steps, Alert } from "antd";
import { PlayCircleOutlined } from "@ant-design/icons";
import { createJob, runJobNow, fetchJobRuns, JobPayload } from "../api/jobs";

const { Text, Paragraph, Title } = Typography;

interface Props {
  open: boolean;
  onClose: () => void;
}

type RunStatus = "idle" | "running" | "success" | "failed";

const TERMINAL = new Set(["success", "failed", "timed_out"]);

async function submitAndPoll(payload: Partial<JobPayload> & { name: string }, timeoutMs = 30000): Promise<{ status: string; jobId: string }> {
  const job = await createJob(payload as JobPayload);
  const jobId = (job as any)._id || (job as any).id;
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const runs = await fetchJobRuns(jobId);
    if (runs.length && TERMINAL.has(runs[0].status)) {
      return { status: runs[0].status, jobId };
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  return { status: "timeout", jobId };
}

async function pollExistingRun(jobId: string, timeoutMs = 30000): Promise<string> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const runs = await fetchJobRuns(jobId);
    if (runs.length && TERMINAL.has(runs[0].status)) {
      return runs[0].status;
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  return "timeout";
}

const EXECUTOR_SPECS: { key: string; label: string; build: () => Partial<JobPayload> & { name: string } }[] = [
  {
    key: "shell",
    label: "shell",
    build: () => ({
      name: `smoke-shell-${Date.now()}`,
      executor: { type: "shell", shell: "bash", script: "echo hydra-smoke-ok" } as any,
      timeout: 30,
    }),
  },
  {
    key: "python",
    label: "python",
    build: () => ({
      name: `smoke-python-${Date.now()}`,
      executor: { type: "python", code: "print('hydra-smoke-ok')" } as any,
      timeout: 60,
    }),
  },
];

function ExecutorSmokeTest() {
  const [statuses, setStatuses] = useState<Record<string, RunStatus>>({});
  const [runningAll, setRunningAll] = useState(false);

  const runOne = async (spec: (typeof EXECUTOR_SPECS)[number]) => {
    setStatuses((s) => ({ ...s, [spec.key]: "running" }));
    try {
      const { status } = await submitAndPoll(spec.build());
      setStatuses((s) => ({ ...s, [spec.key]: status === "success" ? "success" : "failed" }));
    } catch {
      setStatuses((s) => ({ ...s, [spec.key]: "failed" }));
    }
  };

  const runAll = async () => {
    setRunningAll(true);
    await Promise.all(EXECUTOR_SPECS.map(runOne));
    setRunningAll(false);
  };

  const tagFor = (status: RunStatus | undefined) => {
    switch (status) {
      case "running": return <Tag color="processing">running</Tag>;
      case "success": return <Tag color="success">success</Tag>;
      case "failed": return <Tag color="error">failed</Tag>;
      default: return <Tag>idle</Tag>;
    }
  };

  return (
    <div>
      <Title level={5}>Executor Smoke Test</Title>
      <Paragraph type="secondary" style={{ fontSize: 13 }}>
        Submits one job per executor type against the active domain and waits for it to finish. Covers shell and
        python only (zero configuration needed) — for the full matrix including http/sensor/sql/external, use the
        pytest acceptance suite (<Text code>tests/acceptance/</Text>) or the seeded demo jobs.
      </Paragraph>
      <Space direction="vertical" style={{ width: "100%" }}>
        <Button icon={<PlayCircleOutlined />} onClick={runAll} loading={runningAll}>
          Run All
        </Button>
        {EXECUTOR_SPECS.map((spec) => (
          <Space key={spec.key}>
            <Text code style={{ width: 80, display: "inline-block" }}>{spec.label}</Text>
            {tagFor(statuses[spec.key])}
            <Button size="small" onClick={() => runOne(spec)} disabled={statuses[spec.key] === "running"}>
              Run
            </Button>
          </Space>
        ))}
      </Space>
    </div>
  );
}

function DependencyGraphDemo() {
  const [running, setRunning] = useState(false);
  const [stepA, setStepA] = useState<RunStatus>("idle");
  const [stepB, setStepB] = useState<RunStatus>("idle");
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setRunning(true);
    setError(null);
    setStepA("idle");
    setStepB("idle");
    try {
      const ts = Date.now();
      // Neither job auto-runs at creation (schedule.mode "cron" with a
      // next-run a year out) — that leaves a window to create B with A's
      // real _id in depends_on before A executes, then trigger A manually.
      const jobA = await createJob({
        name: `depgraph-demo-a-${ts}`,
        executor: {
          type: "shell",
          shell: "bash",
          script: 'mkdir -p /tmp/hydra-demo && echo "A ran" > /tmp/hydra-demo/depgraph-marker.txt && echo a-done',
        } as any,
        schedule: { mode: "cron", cron: "0 0 1 1 *", enabled: true } as any,
        timeout: 15,
      } as JobPayload);
      const jobAId = (jobA as any)._id || (jobA as any).id;

      const jobB = await createJob({
        name: `depgraph-demo-b-${ts}`,
        depends_on: [jobAId],
        executor: {
          type: "shell",
          shell: "bash",
          script: 'echo "B ran because A succeeded"; cat /tmp/hydra-demo/depgraph-marker.txt 2>/dev/null || echo "(marker not found - B likely ran on a different worker than A)"',
        } as any,
        schedule: { mode: "cron", cron: "0 0 1 1 *", enabled: true } as any,
        timeout: 15,
      } as JobPayload);
      const jobBId = (jobB as any)._id || (jobB as any).id;

      setStepA("running");
      await runJobNow(jobAId);
      const aStatus = await pollExistingRun(jobAId, 30000);
      setStepA(aStatus === "success" ? "success" : "failed");
      if (aStatus !== "success") {
        setError(`Job A did not succeed (status: ${aStatus}) — B is never triggered on a non-success completion.`);
        return;
      }

      setStepB("running");
      // _trigger_dependents only fires on A's run_end event; give the
      // event-ingestion loop a moment before polling B's runs.
      await new Promise((r) => setTimeout(r, 1500));
      const bStatus = await pollExistingRun(jobBId, 30000);
      setStepB(bStatus === "success" ? "success" : "failed");
      if (bStatus === "timeout") {
        setError("Job B never ran — check that at least one worker in this domain is online.");
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setRunning(false);
    }
  };

  const stepStatus = (s: RunStatus): "wait" | "process" | "finish" | "error" => {
    if (s === "idle") return "wait";
    if (s === "running") return "process";
    if (s === "success") return "finish";
    return "error";
  };

  return (
    <div>
      <Title level={5}>Dependency-Graph Demo</Title>
      <Paragraph type="secondary" style={{ fontSize: 13 }}>
        Creates two real jobs (A, B) with B's <Text code>depends_on</Text> set to A's actual generated ID, triggers
        A, and watches B get auto-enqueued only once A succeeds — the one thing the static YAML/template seeds can't
        demonstrate, since <Text code>depends_on</Text> needs a real ID that only exists after creation.
      </Paragraph>
      <Button icon={<PlayCircleOutlined />} onClick={run} loading={running} style={{ marginBottom: 12 }}>
        Run Dependency Demo
      </Button>
      <Steps
        direction="vertical"
        size="small"
        items={[
          { title: "Job A runs", status: stepStatus(stepA) },
          { title: "Job B auto-triggers after A succeeds", status: stepStatus(stepB) },
        ]}
      />
      {error && <Alert type="warning" showIcon message={error} style={{ marginTop: 8 }} />}
    </div>
  );
}

export function DemoToolsDrawer({ open, onClose }: Props) {
  return (
    <Drawer title="Demo Tools" placement="right" width={520} open={open} onClose={onClose}>
      <Space direction="vertical" size={24} style={{ width: "100%" }}>
        <ExecutorSmokeTest />
        <Divider style={{ margin: 0 }} />
        <DependencyGraphDemo />
      </Space>
    </Drawer>
  );
}
