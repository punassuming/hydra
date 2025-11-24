import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Card, Col, Row, Space, Statistic, Table, Tag, Tooltip, Typography, Button } from "antd";
import { fetchWorkers } from "../api/jobs";
import { WorkerInfo } from "../types";
import { apiClient } from "../api/client";
import { useNavigate } from "react-router-dom";

export function WorkersPage() {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["workers"], queryFn: fetchWorkers, refetchInterval: 5000 });
  const navigate = useNavigate();
  const setStateMutation = useMutation({
    mutationFn: ({ workerId, state }: { workerId: string; state: string }) =>
      apiClient.post(`/workers/${workerId}/state`, { state }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["workers"] }),
  });

  const columns = [
    { title: "ID", dataIndex: "worker_id", key: "worker_id" },
    { title: "Domain", dataIndex: "domain", key: "domain" },
    { title: "Host", dataIndex: "hostname", key: "hostname" },
    { title: "IP", dataIndex: "ip", key: "ip" },
    { title: "OS", dataIndex: "os", key: "os" },
    { title: "Deploy", dataIndex: "deployment_type", key: "deployment_type" },
    { title: "Subnet", dataIndex: "subnet", key: "subnet" },
    { title: "Queues", dataIndex: "queues", key: "queues", render: (qs: string[]) => (qs?.length ? qs.join(", ") : "default") },
    {
      title: "Tags",
      dataIndex: "tags",
      key: "tags",
      render: (tags: string[]) => (tags?.length ? tags.map((tag) => <Tag key={tag}>{tag}</Tag>) : "-"),
    },
    {
      title: "Affinity Users",
      dataIndex: "allowed_users",
      key: "allowed_users",
      render: (users: string[]) => (users?.length ? users.join(", ") : "any"),
    },
    {
      title: "Runtime",
      key: "runtime",
      render: (_: unknown, record: WorkerInfo) => (
        <Space size={4} direction="vertical">
          <div>Python: {record.python_version ?? "-"}</div>
          <div>CPU: {record.cpu_count ?? "-"}</div>
          <div>User: {record.run_user ?? "-"}</div>
        </Space>
      ),
    },
    {
      title: "Concurrency",
      key: "concurrency",
      render: (_: unknown, record: WorkerInfo) => (
        <Tooltip title={`Running ${record.current_running} of ${record.max_concurrency}`}>
          <div>
            {record.current_running}/{record.max_concurrency}
          </div>
        </Tooltip>
      ),
    },
    {
      title: "Last heartbeat",
      dataIndex: "last_heartbeat",
      key: "last_heartbeat",
      render: (value?: number) => (value ? new Date(value).toLocaleTimeString() : "-"),
    },
    {
      title: "Status",
      dataIndex: "status",
      key: "status",
      render: (status: string) => <Tag color={status === "online" ? "green" : "volcano"}>{status}</Tag>,
    },
    {
      title: "State",
      key: "state",
      render: (_: unknown, record: WorkerInfo) => (
        <Space>
          <Tag>{record.state ?? "online"}</Tag>
          <Button size="small" onClick={() => setStateMutation.mutate({ workerId: record.worker_id, state: "online" })}>
            Online
          </Button>
          <Button size="small" onClick={() => setStateMutation.mutate({ workerId: record.worker_id, state: "draining" })}>
            Drain
          </Button>
          <Button size="small" danger onClick={() => setStateMutation.mutate({ workerId: record.worker_id, state: "disabled" })}>
            Disable
          </Button>
        </Space>
      ),
    },
    {
      title: "Running Jobs",
      dataIndex: "running_jobs",
      key: "running_jobs",
      render: (jobs: string[]) => (jobs?.length ? jobs.length : 0),
    },
  ];
  const workers = data ?? [];
  const online = workers.filter((w) => w.status === "online").length;
  const totalCapacity = workers.reduce((sum, w) => sum + (w.max_concurrency ?? 0), 0);
  const running = workers.reduce((sum, w) => sum + (w.current_running ?? 0), 0);

  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <Typography.Title level={3} style={{ marginBottom: 0 }}>
        Worker Capabilities
      </Typography.Title>
      <Typography.Text type="secondary">
        Inspect deployments, advertised runtimes, and placement hints to design new affinities.
      </Typography.Text>
      <Row gutter={16}>
        <Col xs={24} md={8}>
          <Card>
            <Statistic title="Workers Online" value={online} suffix={`/ ${workers.length}`} />
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card>
            <Statistic title="Running Tasks" value={running} suffix={`/ ${totalCapacity}`} />
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card>
            <Statistic title="Unique Tags" value={new Set(workers.flatMap((w) => w.tags ?? [])).size} />
          </Card>
        </Col>
      </Row>
      <Card>
        <Table
          dataSource={workers.map((w) => ({ ...w, key: w.worker_id }))}
          columns={columns}
          loading={isLoading}
          pagination={{ pageSize: 10 }}
          size="small"
          onRow={(record) => ({
            onClick: () => navigate(`/workers/${record.worker_id}`),
            style: { cursor: "pointer" },
          })}
        />
      </Card>
    </Space>
  );
}
