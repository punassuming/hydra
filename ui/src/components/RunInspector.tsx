import { useQuery } from "@tanstack/react-query";
import { Drawer, Typography, Space, Divider } from "antd";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { JobRun } from "../types";
import { fetchRun } from "../api/jobs";
import { runStreamUrl } from "../api/client";
import { useActiveDomain } from "../context/ActiveDomainContext";
import { StatusBadge } from "./StatusBadge";
import { LogViewer } from "./LogViewer";
import { FailureInsight } from "./FailureInsight";

interface Props {
  run?: JobRun;
  runId?: string;
  open: boolean;
  onClose: () => void;
}

/**
 * Unified run-detail view — used from JobRuns/History/Observe (given a full
 * `run`) and from a worker's timeline/operations log (given just a `runId`,
 * fetched here). Consolidates what used to be three separate, drifting
 * "show me this run" implementations into one.
 */
export function RunInspector({ run: providedRun, runId, open, onClose }: Props) {
  const { domain } = useActiveDomain();
  const resolvedRunId = providedRun?._id ?? runId;
  const { data: fetchedRun } = useQuery({
    queryKey: ["run", domain, resolvedRunId],
    queryFn: () => fetchRun(resolvedRunId!),
    enabled: open && Boolean(resolvedRunId) && !providedRun,
    // The run may still be in progress; keep its own metadata (status,
    // returncode, etc. — not the log body, which streams separately below)
    // reasonably fresh while the drawer is open.
    refetchInterval: open && !providedRun ? 5000 : false,
  });
  const run = providedRun ?? fetchedRun;

  const [liveLogs, setLiveLogs] = useState<{ stdout: string; stderr: string }>({ stdout: "", stderr: "" });

  useEffect(() => {
    if (!open || !run) {
      return;
    }
    const baseStdout = run.stdout_tail ?? run.stdout ?? "";
    const baseStderr = run.stderr_tail ?? run.stderr ?? "";
    setLiveLogs({ stdout: baseStdout, stderr: baseStderr });

    if (run.status !== "running") {
      return;
    }
    const es = new EventSource(runStreamUrl(run._id));
    es.onmessage = (evt) => {
      try {
        const payload = JSON.parse(evt.data) as { text?: string; stream?: string };
        if (!payload?.text) return;
        setLiveLogs((prev) => {
          const key = payload.stream === "stderr" ? "stderr" : "stdout";
          return { ...prev, [key]: prev[key] + payload.text };
        });
      } catch {
        // ignore malformed chunks
      }
    };
    es.onerror = () => es.close();
    return () => es.close();
    // Re-subscribe only when the drawer opens on a (possibly different) run.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, run?._id, run?.status]);

  return (
    <Drawer title="Run inspector" width={760} open={open} onClose={onClose} destroyOnClose>
      {run ? (
        <Space direction="vertical" style={{ width: "100%" }}>
          <Space wrap>
            <StatusBadge status={run.status} />
            <Typography.Text type="secondary">Run ID: {run._id}</Typography.Text>
            {run.job_id && <Link to={`/jobs/${run.job_id}`}>Open job</Link>}
            {run.worker_id && <Link to={`/workers/${run.worker_id}`}>Open worker</Link>}
          </Space>
          <Typography.Text>
            Started: {run.start_ts ? new Date(run.start_ts).toLocaleString() : "-"} · Finished:{" "}
            {run.end_ts ? new Date(run.end_ts).toLocaleString() : "-"} · Duration:{" "}
            {typeof run.duration === "number" ? `${run.duration.toFixed(1)}s` : "-"}
          </Typography.Text>
          <Typography.Text>
            Exit: {run.returncode ?? "-"} · Reason: {run.completion_reason ?? "-"} · Queue latency:{" "}
            {run.queue_latency_ms ? `${run.queue_latency_ms.toFixed(0)}ms` : "-"}
          </Typography.Text>
          <Divider style={{ margin: "8px 0" }} />
          <LogViewer stdout={liveLogs.stdout} stderr={liveLogs.stderr} maxHeight={420} />
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            Showing tail of last 4KB. Live streaming for running jobs.
          </Typography.Text>
          <FailureInsight
            runId={run._id}
            stdout={liveLogs.stdout || run.stdout || ""}
            stderr={liveLogs.stderr || run.stderr || ""}
            exitCode={run.returncode || 1}
          />
        </Space>
      ) : (
        <Typography.Text type="secondary">{open ? "Loading run…" : "No run selected."}</Typography.Text>
      )}
    </Drawer>
  );
}
