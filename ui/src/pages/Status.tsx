import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Card, Space, Tag, Typography, Button, Progress, Table, Row, Col } from "antd";
import { fetchJobOverview, fetchQueueOverview, runJobNow } from "../api/jobs";
import { JobRun } from "../types";

export function StatusPage() {
  const queryClient = useQueryClient();
  const overviewQuery = useQuery({ queryKey: ["job-overview"], queryFn: fetchJobOverview, refetchInterval: 5000 });
  const queueQuery = useQuery({ queryKey: ["queue-overview"], queryFn: fetchQueueOverview, refetchInterval: 3000 });

  const runNow = useMutation({
    mutationFn: (jobId: string) => runJobNow(jobId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["job-overview"] });
    },
  });

  const renderRunStrip = (runs: JobRun[] | undefined) => {
    const recent = (runs ?? []).slice(0, 10);
    if (!recent.length) return <Typography.Text type="secondary">No runs yet</Typography.Text>;
    const color = (status?: string) =>
      status === "success" ? "#16a34a" : status === "running" ? "#2563eb" : "#f97316";
    return (
      <Space size={6}>
        {recent.map((run, idx) => (
          <div
            key={run._id ?? idx}
            title={`${run.status} · ${run.start_ts ? new Date(run.start_ts).toLocaleString() : "n/a"}`}
            style={{
              width: 12,
              height: 12,
              borderRadius: 3,
              background: color(run.status),
              opacity: idx === 0 ? 1 : 0.7,
            }}
          />
        ))}
      </Space>
    );
  };

  const renderDurationSpark = (runs: JobRun[] | undefined) => {
    const durations = (runs ?? [])
      .map((r) => (typeof r.duration === "number" ? r.duration : null))
      .filter((d): d is number => d !== null);
    if (!durations.length) return <Typography.Text type="secondary">No duration data</Typography.Text>;
    const max = Math.max(...durations, 1);
    return (
      <div style={{ display: "flex", alignItems: "flex-end", gap: 4, height: 40 }}>
        {durations.map((d, idx) => (
          <div
            key={`${d}-${idx}`}
            style={{
              width: 12,
              height: Math.max(6, (d / max) * 36),
              background: "#38bdf8",
              borderRadius: 4,
              opacity: 0.8,
            }}
            title={`~${d.toFixed(1)}s`}
          />
        ))}
      </div>
    );
  };

  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <Card
        title="Status"
        extra={<Typography.Text type="secondary">Status aggregates run health; jump to Jobs for configuration or Workers for placement.</Typography.Text>}
      >
        <Table
          rowKey="job_id"
          loading={overviewQuery.isLoading}
          dataSource={overviewQuery.data ?? []}
          pagination={{ pageSize: 8 }}
          columns={[
            {
              title: "Job",
              dataIndex: "name",
              key: "name",
              render: (_: unknown, job) => {
                const last = job.last_run;
                return (
                  <Space>
                    <Typography.Text strong>{job.name}</Typography.Text>
                    <Tag>{job.schedule_mode}</Tag>
                    {last && (
                      <Tag color={last.status === "success" ? "green" : last.status === "running" ? "blue" : "volcano"}>
                        {last.status}
                      </Tag>
                    )}
                  </Space>
                );
              },
            },
            {
              title: "Success / Failed / Total / Queued",
              key: "counts",
              render: (_: unknown, job) => (
                <Space direction="vertical" size={4}>
                  <div>
                    {job.success_runs} / {job.failed_runs} / {job.total_runs} / {job.queued_runs ?? 0}
                  </div>
                  <Progress
                    percent={job.total_runs ? Math.round((job.success_runs / job.total_runs) * 100) : 0}
                    size="small"
                    status="active"
                  />
                </Space>
              ),
            },
            {
              title: "Recent Runs",
              key: "recent",
              render: (_: unknown, job) => renderRunStrip(job.recent_runs),
            },
            {
              title: "Durations",
              key: "durations",
              render: (_: unknown, job) => renderDurationSpark(job.recent_runs),
            },
            {
              title: "Last Run",
              key: "last",
              render: (_: unknown, job) => {
                const last = job.last_run as JobRun | undefined;
                if (!last) return "-";
                return (
                  <Space direction="vertical" size={2}>
                    <div>{last.start_ts ? new Date(last.start_ts).toLocaleString() : "-"}</div>
                    {typeof last.duration === "number" && <div>{last.duration.toFixed(1)}s</div>}
                  </Space>
                );
              },
            },
            {
              title: "",
              key: "actions",
              render: (_: unknown, job) => (
                <Button size="small" onClick={() => runNow.mutate(job.job_id)} loading={runNow.isPending}>
                  Run Now
                </Button>
              ),
            },
          ]}
        />
      </Card>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={12}>
          <Card title="Queued Jobs" loading={queueQuery.isLoading}>
            <Table
              rowKey="job_id"
              size="small"
              pagination={false}
              dataSource={queueQuery.data?.pending ?? []}
              columns={[
                { title: "Job", dataIndex: "name", key: "name" },
                { title: "Queue", dataIndex: "queue", key: "queue" },
                { title: "Priority", dataIndex: "priority", key: "priority" },
                { title: "User", dataIndex: "user", key: "user" },
              ]}
            />
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="Upcoming (scheduled)" loading={queueQuery.isLoading}>
            <Table
              rowKey="job_id"
              size="small"
              pagination={false}
              dataSource={queueQuery.data?.upcoming ?? []}
              columns={[
                { title: "Job", dataIndex: "name", key: "name" },
                { title: "Queue", dataIndex: "queue", key: "queue" },
                { title: "Priority", dataIndex: "priority", key: "priority" },
                {
                  title: "Next Run",
                  dataIndex: "next_run_at",
                  key: "next_run_at",
                  render: (v?: string) => (v ? new Date(v).toLocaleString() : "-"),
                },
              ]}
            />
          </Card>
        </Col>
      </Row>
    </Space>
  );
}
