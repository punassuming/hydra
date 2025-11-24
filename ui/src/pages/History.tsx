import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Table, Tag, Modal, Typography, Space, Card } from "antd";
import { fetchHistory } from "../api/jobs";
import { JobRun } from "../types";

export function HistoryPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["history"],
    queryFn: fetchHistory,
    refetchInterval: 5000,
  });
  const [logModal, setLogModal] = useState<{ visible: boolean; run?: JobRun }>({ visible: false });

  const columns = [
    { title: "Job", dataIndex: "job_id", key: "job_id" },
    { title: "User", dataIndex: "user", key: "user" },
    {
      title: "Status",
      dataIndex: "status",
      key: "status",
      render: (status: string) => <Tag color={status === "success" ? "green" : status === "running" ? "blue" : "volcano"}>{status}</Tag>,
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

  const runs = (data ?? []).map((run) => ({ ...run, key: run._id }));

  return (
    <Card
      title="Job History"
      extra={<Typography.Text type="secondary">All runs across jobs. Open a run for logs; go to Jobs to edit definitions.</Typography.Text>}
    >
      <Table dataSource={runs} columns={columns} loading={isLoading} size="small" pagination={{ pageSize: 10 }} />
      <Modal open={logModal.visible} onCancel={() => setLogModal({ visible: false })} footer={null} width={800} title="Run Logs">
        {logModal.run ? (
          <Space direction="vertical" style={{ width: "100%" }}>
            <Typography.Text strong>Status: {logModal.run.status}</Typography.Text>
            <Typography.Paragraph>
              <Typography.Text strong>Stdout:</Typography.Text>
              <pre style={{ background: "#f5f5f5", padding: 12, maxHeight: 200, overflow: "auto" }}>
                {logModal.run.stdout_tail ?? logModal.run.stdout ?? "(no stdout)"}
              </pre>
            </Typography.Paragraph>
            <Typography.Paragraph>
              <Typography.Text strong>Stderr:</Typography.Text>
              <pre style={{ background: "#f5f5f5", padding: 12, maxHeight: 200, overflow: "auto" }}>
                {logModal.run.stderr_tail ?? logModal.run.stderr ?? "(no stderr)"}
              </pre>
            </Typography.Paragraph>
          </Space>
        ) : (
          <Typography.Text type="secondary">No logs available.</Typography.Text>
        )}
      </Modal>
    </Card>
  );
}
