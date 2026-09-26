import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Drawer, Form, Input, Modal, Typography, Space, Divider, message } from "antd";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { JobRun } from "../types";
import { backfillJob, fetchRun, runJobNow } from "../api/jobs";
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
  const queryClient = useQueryClient();
  const [messageApi, contextHolder] = message.useMessage();
  const [backfillModalVisible, setBackfillModalVisible] = useState(false);
  const [backfillStartDate, setBackfillStartDate] = useState("");
  const [backfillEndDate, setBackfillEndDate] = useState("");
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

  // Note: runJobNow re-queues the job with its default params, not this
  // run's actual params (JobRun carries no params field to replay) — labeled
  // "Run again" rather than "Retry", which would overpromise.
  const runAgainMutation = useMutation({
    mutationFn: (jobId: string) => runJobNow(jobId),
    onSuccess: () => {
      messageApi.success("Run queued");
      queryClient.invalidateQueries({ queryKey: ["job-runs", domain, run?.job_id] });
    },
    onError: (err: Error) => messageApi.error(err.message),
  });

  const backfillMutation = useMutation({
    mutationFn: ({ id, start, end }: { id: string; start: string; end: string }) => backfillJob(id, start, end),
    onSuccess: (data) => {
      messageApi.success(`Backfill queued: ${data.queued_count} runs (${data.start_date} → ${data.end_date})`);
      queryClient.invalidateQueries({ queryKey: ["job-runs", domain, run?.job_id] });
    },
    onError: (err: Error) => messageApi.error(err.message),
  });

  const openBackfillModal = () => {
    const day = run?.start_ts ? new Date(run.start_ts).toISOString().slice(0, 10) : new Date().toISOString().slice(0, 10);
    setBackfillStartDate(day);
    setBackfillEndDate(day);
    setBackfillModalVisible(true);
  };

  const handleBackfillSubmit = () => {
    if (!run?.job_id || !backfillStartDate || !backfillEndDate) {
      messageApi.error("Please select both start and end dates");
      return;
    }
    backfillMutation.mutate({ id: run.job_id, start: backfillStartDate, end: backfillEndDate });
    setBackfillModalVisible(false);
  };

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
    <>
      {contextHolder}
      <Drawer title="Run inspector" width={760} open={open} onClose={onClose} destroyOnClose>
        {run ? (
        <Space direction="vertical" style={{ width: "100%" }}>
          <Space wrap>
            <StatusBadge status={run.status} />
            <Typography.Text type="secondary">Run ID: {run._id}</Typography.Text>
            {run.job_id && <Link to={`/jobs/${run.job_id}`}>Open job</Link>}
            {run.worker_id && <Link to={`/workers/${run.worker_id}`}>Open worker</Link>}
            {run.job_id && (
              <Button
                size="small"
                loading={runAgainMutation.isPending}
                onClick={() => runAgainMutation.mutate(run.job_id)}
              >
                Run again
              </Button>
            )}
            {run.job_id && (
              <Button size="small" onClick={openBackfillModal}>
                Backfill from here
              </Button>
            )}
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
      <Modal
        open={backfillModalVisible}
        title="Backfill: Queue Historical Runs"
        onOk={handleBackfillSubmit}
        onCancel={() => setBackfillModalVisible(false)}
        okText="Queue Backfill"
        confirmLoading={backfillMutation.isPending}
      >
        <Form layout="vertical">
          <Form.Item label="Start Date" extra="First day of the backfill range (inclusive).">
            <Input type="date" value={backfillStartDate} onChange={(e) => setBackfillStartDate(e.target.value)} />
          </Form.Item>
          <Form.Item label="End Date" extra="Last day of the backfill range (inclusive). Maximum 366 days.">
            <Input type="date" value={backfillEndDate} onChange={(e) => setBackfillEndDate(e.target.value)} />
          </Form.Item>
          <Typography.Text type="secondary">
            One run will be queued per day with <code>HYDRA_EXECUTION_DATE</code> set to each date (YYYY-MM-DD).
          </Typography.Text>
        </Form>
      </Modal>
    </>
  );
}
