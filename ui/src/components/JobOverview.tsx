import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchJobOverview } from "../api/jobs";
import { Card, Table, Tag, Modal, Typography, Space } from "antd";
import { JobOverview as JobOverviewType } from "../types";

export function JobOverview() {
  const { data, isLoading } = useQuery({
    queryKey: ["job-overview"],
    queryFn: fetchJobOverview,
    refetchInterval: 5000,
  });

  const [logModal, setLogModal] = useState<{ visible: boolean; run?: JobOverviewType["last_run"]; jobName?: string }>({
    visible: false,
  });

  const rows = useMemo(
    () => (data ?? []).map((item) => ({ ...item, key: item.job_id })),
    [data],
  );

  const columns = [
    { title: "Job", dataIndex: "name", key: "name" },
    {
      title: "Schedule",
      dataIndex: "schedule_mode",
      key: "schedule_mode",
      render: (mode: string) => <Tag>{mode}</Tag>,
    },
    { title: "Total Runs", dataIndex: "total_runs", key: "total_runs" },
    {
      title: "Success",
      dataIndex: "success_runs",
      key: "success_runs",
      render: (value: number, record: JobOverviewType) => (
        <Typography.Text type={value > 0 ? "success" : undefined}>{value}</Typography.Text>
      ),
    },
    {
      title: "Failed",
      dataIndex: "failed_runs",
      key: "failed_runs",
      render: (value: number) => <Typography.Text type={value > 0 ? "danger" : undefined}>{value}</Typography.Text>,
    },
    {
      title: "Last Run",
      key: "last_run",
      render: (_: unknown, record: JobOverviewType) =>
        record.last_run ? new Date(record.last_run.start_ts || record.last_run.scheduled_ts || "").toLocaleString() : "-",
    },
    {
      title: "",
      key: "actions",
      render: (_: unknown, record: JobOverviewType) => (
        <Typography.Link
          onClick={() =>
            setLogModal({
              visible: true,
              run: record.last_run,
              jobName: record.name,
            })
          }
          disabled={!record.last_run}
        >
          View Logs
        </Typography.Link>
      ),
    },
  ];

  return (
    <>
      <Card title="Job Overview" bordered={false}>
        <Table dataSource={rows} columns={columns} loading={isLoading} pagination={{ pageSize: 5 }} size="small" />
      </Card>
      <Modal
        open={logModal.visible}
        title={`Logs - ${logModal.jobName ?? ""}`}
        onCancel={() => setLogModal({ visible: false })}
        footer={null}
        width={800}
      >
        {logModal.run ? (
          <Space direction="vertical" style={{ width: "100%" }}>
            <Typography.Text strong>Status: {logModal.run.status}</Typography.Text>
            <Typography.Paragraph>
              <Typography.Text strong>Stdout:</Typography.Text>
              <pre style={{ background: "#f5f5f5", padding: 12 }}>
                {logModal.run.stdout_tail ?? logModal.run.stdout ?? "(no stdout)"}{" "}
              </pre>
            </Typography.Paragraph>
            <Typography.Paragraph>
              <Typography.Text strong>Stderr:</Typography.Text>
              <pre style={{ background: "#f5f5f5", padding: 12 }}>
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
