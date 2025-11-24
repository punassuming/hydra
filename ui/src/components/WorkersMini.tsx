import { Card, Col, Row, Space, Tag, Typography, Skeleton } from "antd";
import { useQuery } from "@tanstack/react-query";
import { fetchWorkers } from "../api/jobs";
import { Link } from "react-router-dom";

export function WorkersMini() {
  const { data, isLoading } = useQuery({ queryKey: ["workers"], queryFn: fetchWorkers, refetchInterval: 8000 });
  const workers = data ?? [];

  return (
    <Card
      title={
        <Space>
          <Typography.Text strong>Workers</Typography.Text>
          <Tag color="geekblue">
            {workers.length} online / <Link to="/workers">view all</Link>
          </Tag>
        </Space>
      }
      bordered={false}
    >
      {isLoading ? (
        <Skeleton active paragraph={{ rows: 2 }} />
      ) : (
        <Row gutter={[12, 12]}>
          {workers.slice(0, 4).map((w) => (
            <Col key={w.worker_id} xs={24} sm={12} md={12} lg={12}>
              <Card size="small" bordered style={{ minHeight: 120 }}>
                <Space direction="vertical" size={4}>
                  <Space>
                    <Typography.Text strong>{w.worker_id}</Typography.Text>
                    <Tag color={w.status === "online" ? "green" : "volcano"}>{w.status}</Tag>
                  </Space>
                  <div>{w.hostname || w.worker_id}</div>
                  <div>Queues: {(w.queues ?? ["default"]).join(", ")}</div>
                  <div>
                    Running: {w.current_running}/{w.max_concurrency}
                  </div>
                  <Link to="/workers">Details</Link>
                </Space>
              </Card>
            </Col>
          ))}
        </Row>
      )}
    </Card>
  );
}
