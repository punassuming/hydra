import { useQuery } from "@tanstack/react-query";
import { Card, Table, Tag } from "antd";
import { fetchJobGrid } from "../api/jobs";

interface Props {
  jobId: string;
}

export function JobGridView({ jobId }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ["job-grid", jobId],
    queryFn: () => fetchJobGrid(jobId),
    enabled: Boolean(jobId),
    refetchInterval: 5000,
  });

  const columns = [
    { title: "Run ID", dataIndex: "run_id", key: "run_id" },
    {
      title: "Status",
      dataIndex: "status",
      key: "status",
      render: (status?: string) => <Tag color={status === "success" ? "green" : status === "running" ? "blue" : "volcano"}>{status}</Tag>,
    },
    { title: "Start", dataIndex: "start_ts", key: "start_ts" },
    { title: "End", dataIndex: "end_ts", key: "end_ts" },
    {
      title: "Duration (s)",
      dataIndex: "duration",
      key: "duration",
      render: (value?: number) => (value != null ? value.toFixed(1) : "-"),
    },
  ];

  return (
    <Card>
      <Table dataSource={(data?.runs ?? []).map((run) => ({ ...run, key: run.run_id }))} columns={columns} loading={isLoading} pagination={false} />
    </Card>
  );
}
