import { useQuery } from "@tanstack/react-query";
import { Card, Table, Tag, Progress, Tooltip } from "antd";
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
    { title: "Host", dataIndex: "hostname", key: "hostname" },
    { title: "IP", dataIndex: "ip", key: "ip" },
    { title: "Deploy", dataIndex: "deployment_type", key: "deployment_type" },
    { title: "State", dataIndex: "state", key: "state", render: (state: string) => <Tag>{state || "online"}</Tag> },
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
        <Tooltip
          title={
            <>
              <div>CPU: {record.cpu_count ?? "-"}</div>
              <div>Python: {record.python_version ?? "-"}</div>
              <div>CWD: {record.cwd ?? "-"}</div>
              <div>User: {record.run_user ?? "-"}</div>
              <div>Subnet: {record.subnet ?? "-"}</div>
            </>
          }
        >
          <Progress
            size="small"
            percent={Math.round((record.current_running / Math.max(record.max_concurrency, 1)) * 100)}
            format={() => `${record.current_running}/${record.max_concurrency}`}
          />
        </Tooltip>
      ),
    },
    {
      title: "Status",
      dataIndex: "status",
      key: "status",
      render: (status: string) => <Tag color={status === "online" ? "green" : "volcano"}>{status}</Tag>,
    },
    {
      title: "Running Jobs",
      dataIndex: "running_jobs",
      key: "running_jobs",
      render: (jobs: string[]) => (jobs?.length ? jobs.length : 0),
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
