import { useQuery } from "@tanstack/react-query";
import { Table, Tag, Modal, Typography, Space, Divider } from "antd";
import { JobRun } from "../types";
import { fetchJobRuns } from "../api/jobs";
import { useEffect, useState } from "react";
import { runStreamUrl } from "../api/client";
import { Link } from "react-router-dom";

interface Props {
  jobId?: string | null;
  runs?: JobRun[];
  loading?: boolean;
}

export function JobRuns({ jobId, runs: providedRuns, loading }: Props) {
  const enabled = Boolean(jobId);
  const shouldQuery = !providedRuns && enabled;
  const { data, isLoading } = useQuery({
    queryKey: ["job-runs", jobId],
    queryFn: () => fetchJobRuns(jobId!),
    enabled: shouldQuery,
    refetchInterval: shouldQuery ? 5000 : false,
  });
  const [logModal, setLogModal] = useState<{ visible: boolean; run?: JobRun }>({ visible: false });
  const [liveLogs, setLiveLogs] = useState<{ stdout: string; stderr: string }>({ stdout: "", stderr: "" });
  const [source, setSource] = useState<EventSource | null>(null);

  useEffect(() => {
    if (!logModal.visible || !logModal.run) {
      source?.close();
      setSource(null);
      return;
    }
    const baseStdout = logModal.run.stdout_tail ?? logModal.run.stdout ?? "";
    const baseStderr = logModal.run.stderr_tail ?? logModal.run.stderr ?? "";
    setLiveLogs({ stdout: baseStdout, stderr: baseStderr });

    if (logModal.run.status !== "running") {
      return;
    }
    const es = new EventSource(runStreamUrl(logModal.run._id));
    es.onmessage = (evt) => {
      try {
        const payload = JSON.parse(evt.data) as { text?: string; stream?: string };
        if (!payload?.text) return;
        setLiveLogs((prev) => {
          const key = payload.stream === "stderr" ? "stderr" : "stdout";
          return { ...prev, [key]: (prev as any)[key] + payload.text };
        });
      } catch {
        // ignore
      }
    };
    es.onerror = () => {
      es.close();
      setSource(null);
    };
    setSource(es);
    return () => {
      es.close();
      setSource(null);
    };
  }, [logModal]);

  const columns = [
    {
      title: "Job",
      dataIndex: "job_id",
      key: "job_id",
      render: (value: string) => (value ? <Link to={`/jobs/${value}`}>{value.slice(0, 8)}</Link> : "-"),
      hidden: Boolean(jobId),
    },
    {
      title: "Status",
      dataIndex: "status",
      key: "status",
      render: (status: string) => <Tag color={status === "success" ? "green" : status === "running" ? "blue" : "volcano"}>{status}</Tag>,
    },
    { title: "Worker", dataIndex: "worker_id", key: "worker_id" },
    { title: "Slot", dataIndex: "slot", key: "slot" },
    { title: "Attempt", dataIndex: "attempt", key: "attempt" },
    {
      title: "Queued (ms)",
      dataIndex: "queue_latency_ms",
      key: "queue_latency_ms",
      render: (value?: number) => (value !== undefined ? value.toFixed(0) : "-"),
    },
    {
      title: "Queued At",
      dataIndex: "scheduled_ts",
      key: "scheduled_ts",
      render: (value?: string) => (value ? new Date(value).toLocaleTimeString() : "-"),
    },
    {
      title: "Started",
      dataIndex: "start_ts",
      key: "start_ts",
      render: (value?: string) => (value ? new Date(value).toLocaleTimeString() : "-"),
    },
    {
      title: "Finished",
      dataIndex: "end_ts",
      key: "end_ts",
      render: (value?: string) => (value ? new Date(value).toLocaleTimeString() : "-"),
    },
    { title: "Reason", dataIndex: "completion_reason", key: "completion_reason" },
    {
      title: "",
      key: "logs",
      render: (_: unknown, record: any) => (
        <Typography.Link onClick={() => setLogModal({ visible: true, run: record })}>View Logs</Typography.Link>
      ),
    },
  ];

  const combinedRuns = (providedRuns ?? data ?? []).map((run) => ({ ...run, key: run._id }));
  const tableLoading = typeof loading === "boolean" ? loading : isLoading;
  const visibleColumns = columns.filter((col: any) => !col.hidden);

  return (
    <>
      {!jobId && !providedRuns ? (
        <p>Select a job to view run history.</p>
      ) : (
        <Table dataSource={combinedRuns} columns={visibleColumns} loading={tableLoading} pagination={{ pageSize: 10 }} size="small" />
      )}
      <Modal open={!!logModal?.visible} onCancel={() => setLogModal({ visible: false })} footer={null} width={900} title="Run Logs">
        {logModal?.run ? (
          <Space direction="vertical" style={{ width: "100%" }}>
            <Space>
              <Tag color={logModal.run.status === "success" ? "green" : logModal.run.status === "running" ? "blue" : "volcano"}>
                {logModal.run.status}
              </Tag>
              <Typography.Text type="secondary">Run ID: {logModal.run._id}</Typography.Text>
              {logModal.run.worker_id && <Typography.Text type="secondary">Worker: {logModal.run.worker_id}</Typography.Text>}
            </Space>
            <Typography.Text>
              Started: {logModal.run.start_ts ? new Date(logModal.run.start_ts).toLocaleString() : "-"} · Finished:{" "}
              {logModal.run.end_ts ? new Date(logModal.run.end_ts).toLocaleString() : "-"} · Duration:{" "}
              {typeof logModal.run.duration === "number" ? `${logModal.run.duration.toFixed(1)}s` : "-"}
            </Typography.Text>
            <Typography.Text>
              Exit: {logModal.run.returncode ?? "-"} · Reason: {logModal.run.completion_reason ?? "-"} · Queue latency:{" "}
              {logModal.run.queue_latency_ms ? `${logModal.run.queue_latency_ms.toFixed(0)}ms` : "-"}
            </Typography.Text>
            <Divider />
            <Typography.Paragraph>
              <Typography.Text strong>Stdout:</Typography.Text>
              <pre style={{ background: "#f5f5f5", padding: 12, maxHeight: 240, overflow: "auto" }}>
                {liveLogs.stdout || "(no stdout)"}
              </pre>
              <Typography.Text type="secondary">Showing tail of last 4KB.</Typography.Text>
            </Typography.Paragraph>
            <Typography.Paragraph>
              <Typography.Text strong>Stderr:</Typography.Text>
              <pre style={{ background: "#f5f5f5", padding: 12, maxHeight: 240, overflow: "auto" }}>
                {liveLogs.stderr || "(no stderr)"}
              </pre>
            </Typography.Paragraph>
          </Space>
        ) : (
          <Typography.Text type="secondary">No logs available.</Typography.Text>
        )}
      </Modal>
    </>
  );
}
