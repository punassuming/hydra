import { useQuery } from "@tanstack/react-query";
import { Table, Typography, Space, Button } from "antd";
import { JobRun } from "../types";
import { fetchJobRuns } from "../api/jobs";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useActiveDomain } from "../context/ActiveDomainContext";
import { StatusBadge } from "./StatusBadge";
import { RunInspector } from "./RunInspector";

interface Props {
  jobId?: string | null;
  runs?: JobRun[];
  loading?: boolean;
  onKillRun?: (runId: string) => void;
}

export function JobRuns({ jobId, runs: providedRuns, loading, onKillRun }: Props) {
  const { domain } = useActiveDomain();
  const enabled = Boolean(jobId);
  const shouldQuery = !providedRuns && enabled;
  const { data, isLoading } = useQuery({
    queryKey: ["job-runs", domain, jobId],
    queryFn: () => fetchJobRuns(jobId!),
    enabled: shouldQuery,
    refetchInterval: shouldQuery ? 5000 : false,
  });
  const [logModal, setLogModal] = useState<{ visible: boolean; run?: JobRun }>({ visible: false });

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
      render: (status: string) => <StatusBadge status={status} />,
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
      key: "actions",
      render: (_: unknown, record: any) => (
        <Space>
          <Typography.Link onClick={() => setLogModal({ visible: true, run: record })}>Inspect</Typography.Link>
          {record.status === "running" && onKillRun && (
            <Button size="small" danger onClick={() => onKillRun(record._id)}>Stop</Button>
          )}
        </Space>
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
      <RunInspector run={logModal.run} open={logModal.visible} onClose={() => setLogModal({ visible: false })} />
    </>
  );
}
