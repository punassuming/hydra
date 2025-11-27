import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Card, Col, Descriptions, Row, Space, Statistic, Tag, Typography, Button, List } from "antd";
import { useNavigate, useParams } from "react-router-dom";
import { fetchWorkers } from "../api/jobs";
import { apiClient } from "../api/client";
import { WorkerInfo } from "../types";

export function WorkerDetailPage() {
  const { workerId } = useParams<{ workerId: string }>();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { data, isLoading } = useQuery({ queryKey: ["workers"], queryFn: fetchWorkers, refetchInterval: 5000 });
  const worker = data?.find((w) => w.worker_id === workerId);

  const setStateMutation = useMutation({
    mutationFn: (state: string) => apiClient.post(`/workers/${workerId}/state`, { state }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["workers"] }),
  });

  if (!workerId) {
    return <Typography.Text>Please choose a worker from the list.</Typography.Text>;
  }

  if (isLoading) {
    return <Typography.Text>Loading worker…</Typography.Text>;
  }

  if (!worker) {
    return (
      <Space direction="vertical">
        <Typography.Text>Worker {workerId} not found.</Typography.Text>
        <Button onClick={() => navigate("/workers")}>Back to Workers</Button>
      </Space>
    );
  }

  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <Space align="center" wrap>
        <Typography.Title level={3} style={{ marginBottom: 0 }}>
          {worker.worker_id}
        </Typography.Title>
        <Tag color={worker.status === "online" ? "green" : "volcano"}>{worker.status}</Tag>
        <Tag>{worker.state ?? "online"}</Tag>
        <Button onClick={() => navigate("/workers")}>Back</Button>
      </Space>

      <Row gutter={16}>
        <Col xs={24} md={8}>
          <Card>
            <Statistic title="Concurrency" value={`${worker.current_running ?? 0}/${worker.max_concurrency ?? 0}`} />
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card>
            <Statistic title="Allowed Users" value={worker.allowed_users?.length ? worker.allowed_users.join(", ") : "any"} />
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card>
            <Statistic title="Tags" value={(worker.tags ?? []).length} />
          </Card>
        </Col>
      </Row>

      <Card title="Details">
        <Descriptions bordered column={1} size="small">
          <Descriptions.Item label="Domain">{worker.domain}</Descriptions.Item>
          <Descriptions.Item label="Hostname">{worker.hostname || "-"}</Descriptions.Item>
          <Descriptions.Item label="IP">{worker.ip || "-"}</Descriptions.Item>
          <Descriptions.Item label="OS">{worker.os || "-"}</Descriptions.Item>
          <Descriptions.Item label="Deployment">{worker.deployment_type || "-"}</Descriptions.Item>
          <Descriptions.Item label="Subnet">{worker.subnet || "-"}</Descriptions.Item>
          <Descriptions.Item label="Python">{worker.python_version || "-"}</Descriptions.Item>
          <Descriptions.Item label="Run User">{worker.run_user || "-"}</Descriptions.Item>
          <Descriptions.Item label="Last heartbeat">
            {worker.last_heartbeat ? new Date(worker.last_heartbeat).toLocaleString() : "-"}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card
        title="Affinity tags"
        extra={
          <Space>
            <Button size="small" onClick={() => setStateMutation.mutate("online")} loading={setStateMutation.isPending}>
              Online
            </Button>
            <Button size="small" onClick={() => setStateMutation.mutate("draining")} loading={setStateMutation.isPending}>
              Drain
            </Button>
            <Button
              size="small"
              danger
              onClick={() => setStateMutation.mutate("disabled")}
              loading={setStateMutation.isPending}
            >
              Disable
            </Button>
          </Space>
        }
      >
        <Space wrap>
          {(worker.tags ?? []).map((t) => (
            <Tag key={t}>{t}</Tag>
          ))}
          {!(worker.tags ?? []).length && <Typography.Text type="secondary">No tags advertised.</Typography.Text>}
        </Space>
        <Typography.Paragraph style={{ marginTop: 12, marginBottom: 0 }}>
          Allowed users: {worker.allowed_users?.length ? worker.allowed_users.join(", ") : "any"}
        </Typography.Paragraph>
      </Card>

      <Card title="Running jobs">
        <List
          dataSource={worker.running_jobs ?? []}
          locale={{ emptyText: "No running jobs on this worker." }}
          renderItem={(jobId: string) => <List.Item>{jobId}</List.Item>}
        />
      </Card>
    </Space>
  );
}
