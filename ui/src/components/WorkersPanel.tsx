import { useQuery } from "@tanstack/react-query";
import { Card, Table, Tag, Progress } from "antd";
import { fetchWorkers } from "../api/jobs";

export function WorkersPanel() {
  const { data, isLoading } = useQuery({
    queryKey: ["workers"],
    queryFn: fetchWorkers,
    refetchInterval: 5000,
  });

  const columns = [
    { title: "ID", dataIndex: "worker_id", key: "worker_id" },
    { title: "OS", dataIndex: "os", key: "os" },
    {
      title: "Tags",
      dataIndex: "tags",
      key: "tags",
      render: (tags: string[]) => (tags.length ? tags.map((tag) => <Tag key={tag}>{tag}</Tag>) : "-"),
    },
    {
      title: "Concurrency",
      key: "concurrency",
      render: (_: unknown, record: any) => (
        <Progress
          size="small"
          percent={Math.round((record.current_running / Math.max(record.max_concurrency, 1)) * 100)}
          format={() => `${record.current_running}/${record.max_concurrency}`}
        />
      ),
    },
    {
      title: "Status",
      dataIndex: "status",
      key: "status",
      render: (status: string) => <Tag color={status === "online" ? "green" : "volcano"}>{status}</Tag>,
    },
  ];

  return (
    <Card title="Workers" bordered={false}>
      <Table
        size="small"
        loading={isLoading}
        dataSource={(data ?? []).map((worker) => ({ ...worker, key: worker.worker_id }))}
        columns={columns}
        pagination={false}
      />
    </Card>
  );
}
