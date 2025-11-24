import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Card, Descriptions, Space, Tag, Typography, List, Button } from "antd";
import { fetchWorkers } from "../api/jobs";

export function WorkerDetailPage() {
  const { workerId } = useParams();
  const { data, isLoading } = useQuery({ queryKey: ["workers"], queryFn: fetchWorkers, refetchInterval: 5000 });
  const worker = (data ?? []).find((w) => w.worker_id === workerId);

  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <Typography.Title level={3} style={{ marginBottom: 0 }}>
        Worker {workerId}
      </Typography.Title>
      <Typography.Text type="secondary">
        Live metadata and current running jobs. Use the Workers page to change state or queues.
      </Typography.Text>
      <Button size="small">
        <Link to="/workers">Back to Workers</Link>
      </Button>
      <Card loading={isLoading || !worker} title="Details">
        {worker ? (
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="Status">
              <Tag color={worker.status === "online" ? "green" : "volcano"}>{worker.status}</Tag> <Tag>{worker.state ?? "online"}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="Host">{worker.hostname}</Descriptions.Item>
            <Descriptions.Item label="IP">{worker.ip}</Descriptions.Item>
            <Descriptions.Item label="OS">{worker.os}</Descriptions.Item>
            <Descriptions.Item label="Deploy">{worker.deployment_type}</Descriptions.Item>
            <Descriptions.Item label="Subnet">{worker.subnet}</Descriptions.Item>
            <Descriptions.Item label="Queues">{(worker.queues ?? ["default"]).join(", ")}</Descriptions.Item>
            <Descriptions.Item label="Tags">{worker.tags.join(", ") || "-"}</Descriptions.Item>
            <Descriptions.Item label="Allowed Users">{worker.allowed_users.join(", ") || "any"}</Descriptions.Item>
            <Descriptions.Item label="Runtime">
              CPU {worker.cpu_count ?? "-"} · Python {worker.python_version ?? "-"} · User {worker.run_user ?? "-"}
            </Descriptions.Item>
            <Descriptions.Item label="Concurrency">
              {worker.current_running}/{worker.max_concurrency}
            </Descriptions.Item>
            <Descriptions.Item label="Last Heartbeat">
              {worker.last_heartbeat ? new Date(worker.last_heartbeat).toLocaleString() : "-"}
            </Descriptions.Item>
          </Descriptions>
        ) : (
          <Typography.Text>Worker not found.</Typography.Text>
        )}
      </Card>
      <Card title="Running Jobs">
        <List
          loading={isLoading}
          dataSource={worker?.running_jobs ?? []}
          renderItem={(jobId) => (
            <List.Item>
              <Space>
                <Typography.Text>Job</Typography.Text>
                <Link to={`/jobs/${jobId}`}>{jobId}</Link>
              </Space>
            </List.Item>
          )}
        />
      </Card>
    </Space>
  );
}
