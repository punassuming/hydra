import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Card, Table, Tag, Modal, Typography, Space } from "antd";
import { fetchJobRuns } from "../api/jobs";

interface Props {
  jobId?: string | null;
}

export function JobRuns({ jobId }: Props) {
  const enabled = Boolean(jobId);
  const { data, isLoading } = useQuery({
    queryKey: ["job-runs", jobId],
    queryFn: () => fetchJobRuns(jobId!),
    enabled,
    refetchInterval: enabled ? 5000 : false,
  });

  const [logModal, setLogModal] = useState<{ visible: boolean; run?: (typeof data)[number] } | undefined>({
    visible: false,
  });

  const columns = [
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

  const runs = (data ?? []).map((run) => ({ ...run, key: run._id }));

  return (
    <>
      <Card title="Job History" bordered={false}>
        {!jobId ? (
          <p>Select a job to view run history.</p>
        ) : (
          <Table dataSource={runs} columns={columns} loading={isLoading} pagination={{ pageSize: 5 }} size="small" />
        )}
      </Card>
      <Modal open={!!logModal?.visible} onCancel={() => setLogModal({ visible: false })} footer={null} width={800} title="Run Logs">
        {logModal?.run ? (
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
    </>
  );
}
