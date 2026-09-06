import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Table, Modal, Typography, Space, Card } from "antd";
import { fetchHistory } from "../api/jobs";
import { JobRun } from "../types";
import { useActiveDomain } from "../context/ActiveDomainContext";
import { StatusBadge } from "../components/StatusBadge";
import { LogViewer } from "../components/LogViewer";
import { FailureInsight } from "../components/FailureInsight";

export function HistoryPage() {
  const { domain } = useActiveDomain();
  const { data, isLoading } = useQuery({
    queryKey: ["history", domain],
    queryFn: () => fetchHistory(),
    refetchInterval: 5000,
  });
  const [logModal, setLogModal] = useState<{ visible: boolean; run?: JobRun }>({ visible: false });

  const columns = [
    { title: "Job", dataIndex: "job_id", key: "job_id" },
    { title: "User", dataIndex: "user", key: "user" },
    { title: "Domain", dataIndex: "domain", key: "domain", render: (value?: string) => value ?? "prod" },
    {
      title: "Status",
      dataIndex: "status",
      key: "status",
      render: (status: string) => <StatusBadge status={status} />,
    },
    { title: "Worker", dataIndex: "worker_id", key: "worker_id" },
    {
      title: "Started",
      dataIndex: "start_ts",
      key: "start_ts",
      render: (value?: string) => (value ? new Date(value).toLocaleString() : "-"),
    },
    {
      title: "Finished",
      dataIndex: "end_ts",
      key: "end_ts",
      render: (value?: string) => (value ? new Date(value).toLocaleString() : "-"),
    },
    {
      title: "Logs",
      key: "logs",
      render: (_: unknown, record: JobRun) => (
        <Typography.Link onClick={() => setLogModal({ visible: true, run: record })}>View Logs</Typography.Link>
      ),
    },
  ];

  const runs = (data?.items ?? []).map((run) => ({ ...run, key: run._id }));

  return (
    <Card
      title="Job History"
      extra={<Typography.Text type="secondary">All runs across jobs. Open a run for logs; go to Jobs to edit definitions.</Typography.Text>}
    >
      <Table dataSource={runs} columns={columns} loading={isLoading} size="small" pagination={{ pageSize: 10 }} />
      <Modal open={logModal.visible} onCancel={() => setLogModal({ visible: false })} footer={null} width={1000} title="Run Logs">
        {logModal.run ? (
          <Space direction="vertical" style={{ width: "100%" }}>
            <Space>
              <StatusBadge status={logModal.run.status} />
              <Typography.Text type="secondary">Run ID: {logModal.run._id}</Typography.Text>
              {logModal.run.worker_id && <Typography.Text type="secondary">Worker: {logModal.run.worker_id}</Typography.Text>}
            </Space>
            <Typography.Text>
              Started: {logModal.run.start_ts ? new Date(logModal.run.start_ts).toLocaleString() : "-"} · 
              Finished: {logModal.run.end_ts ? new Date(logModal.run.end_ts).toLocaleString() : "-"} · 
              Duration: {typeof logModal.run.duration === "number" ? `${logModal.run.duration.toFixed(1)}s` : "-"}
            </Typography.Text>
            <LogViewer
              stdout={logModal.run.stdout_tail ?? logModal.run.stdout}
              stderr={logModal.run.stderr_tail ?? logModal.run.stderr}
              maxHeight={400}
            />
            <FailureInsight
              runId={logModal.run._id}
              stdout={logModal.run.stdout || ""}
              stderr={logModal.run.stderr || ""}
              exitCode={logModal.run.returncode || 1}
            />
          </Space>
        ) : (
          <Typography.Text type="secondary">No logs available.</Typography.Text>
        )}
      </Modal>
    </Card>
  );
}
