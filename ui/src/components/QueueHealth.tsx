import { Card, Space, Typography, Alert, Progress, Table, Tag, Tooltip } from "antd";
import { useQuery } from "@tanstack/react-query";
import { fetchQueuePressure } from "../api/jobs";
import { useActiveDomain } from "../context/ActiveDomainContext";
import { DomainPressure } from "../types";

export function QueueHealth() {
  const { domain } = useActiveDomain();
  const pressureQuery = useQuery({
    queryKey: ["queue-pressure", domain],
    queryFn: fetchQueuePressure,
    refetchInterval: 5000,
  });

  const domains = pressureQuery.data?.domains ?? [];
  const totalStalled = domains.reduce((sum, d) => sum + d.stalled_count, 0);

  const columns = [
    { title: "Domain", dataIndex: "domain", key: "domain" },
    {
      title: "Pending Backlog",
      key: "pending_total",
      render: (_: unknown, d: DomainPressure) => d.pending_total,
    },
    {
      title: "Starved Jobs",
      key: "stalled",
      render: (_: unknown, d: DomainPressure) =>
        d.stalled_count > 0 ? (
          <Tooltip title={`No worker has picked these up for ${d.starvation_threshold}+ scheduling ticks: ${d.stalled_jobs.join(", ")}`}>
            <Tag color="error">{d.stalled_count} stalled</Tag>
          </Tooltip>
        ) : (
          <Tag color="success">none</Tag>
        ),
    },
    {
      title: "Worker Queue Depth",
      key: "worker_queue_depth",
      render: (_: unknown, d: DomainPressure) => d.total_worker_queue_depth,
    },
    {
      title: "Capacity Utilization",
      key: "capacity",
      render: (_: unknown, d: DomainPressure) => {
        const pct = d.total_capacity > 0 ? Math.round((d.total_running / d.total_capacity) * 100) : 0;
        return (
          <Tooltip title={`${d.total_running} running / ${d.total_capacity} capacity across ${d.online_workers} online worker(s)`}>
            <Progress
              percent={Math.min(pct, 100)}
              size="small"
              status={pct >= 100 ? "exception" : "active"}
              style={{ width: 140 }}
            />
          </Tooltip>
        );
      },
    },
  ];

  return (
    <Card
      title={<Typography.Text strong>Queue Health</Typography.Text>}
      loading={pressureQuery.isLoading}
    >
      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
        {totalStalled > 0 && (
          <Alert
            type="warning"
            showIcon
            message={`${totalStalled} job(s) are starved for workers`}
            description="These jobs have been pending without a matching worker for multiple scheduling ticks. Check worker affinity, tags, or capacity."
          />
        )}
        <Table<DomainPressure>
          dataSource={domains.map((d) => ({ ...d, key: d.domain }))}
          columns={columns}
          pagination={false}
          size="small"
          locale={{ emptyText: "No queue pressure data available." }}
        />
      </Space>
    </Card>
  );
}
