import { Row, Col, Card, Typography, Space, List, Empty } from "antd";
import { useQuery } from "@tanstack/react-query";
import { fetchJobOverview, fetchHistory } from "../api/jobs";
import { useActiveDomain } from "../context/ActiveDomainContext";
import { MetricCard } from "./MetricCard";
import { StatusBadge } from "./StatusBadge";
import { Link } from "react-router-dom";
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  SyncOutlined,
  ClockCircleOutlined,
  AlertOutlined,
} from "@ant-design/icons";
import { useTheme } from "../theme";

export function JobsDashboard() {
  const { domain } = useActiveDomain();
  const { colors } = useTheme();
  const overviewQuery = useQuery({
    queryKey: ["job-overview", domain],
    queryFn: fetchJobOverview,
    refetchInterval: 5000,
  });

  const historyQuery = useQuery({
    queryKey: ["history", domain],
    queryFn: () => fetchHistory(),
    refetchInterval: 5000,
  });

  const overview = overviewQuery.data ?? [];
  const history = historyQuery.data?.items ?? [];

  // Calculate metrics
  const totalJobs = overview.length;
  const totalRuns = overview.reduce((acc, job) => acc + job.total_runs, 0);
  const successRuns = overview.reduce((acc, job) => acc + job.success_runs, 0);
  const failedRuns = overview.reduce((acc, job) => acc + job.failed_runs, 0);
  const runningRuns = history.filter((run) => run.status === "running").length;

  // Get recently failed runs
  const failedJobRuns = history
    .filter((run) => run.status === "failed")
    .slice(0, 5);

  const successRate = totalRuns > 0 ? ((successRuns / totalRuns) * 100).toFixed(1) : "0";

  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} md={6}>
          <MetricCard
            title="Total Jobs"
            value={totalJobs}
            loading={overviewQuery.isLoading}
            prefix={<ClockCircleOutlined />}
            tooltip="Total number of jobs configured in the system"
          />
        </Col>
        <Col xs={24} sm={12} md={6}>
          <MetricCard
            title="Success Rate"
            value={`${successRate}%`}
            loading={overviewQuery.isLoading}
            prefix={<CheckCircleOutlined />}
            tooltip="Percentage of successful runs"
            valueStyle={{ color: colors.success }}
          />
        </Col>
        <Col xs={24} sm={12} md={6}>
          <MetricCard
            title="Failed Runs"
            value={failedRuns}
            loading={overviewQuery.isLoading}
            prefix={<CloseCircleOutlined />}
            tooltip="Total number of failed runs"
            valueStyle={{ color: colors.error }}
          />
        </Col>
        <Col xs={24} sm={12} md={6}>
          <MetricCard
            title="Running Now"
            value={runningRuns}
            loading={historyQuery.isLoading}
            prefix={<SyncOutlined spin />}
            tooltip="Jobs currently running"
            valueStyle={{ color: colors.info }}
          />
        </Col>
      </Row>

      <Card
        title={
          <Space>
            <AlertOutlined style={{ color: colors.error }} />
            <Typography.Text strong>Recently Failed Jobs</Typography.Text>
          </Space>
        }
        extra={<Link to="/observe">View All History</Link>}
        loading={historyQuery.isLoading}
      >
        {failedJobRuns.length > 0 ? (
          <List
            dataSource={failedJobRuns}
            renderItem={(run) => (
              <List.Item
                key={run._id}
                actions={[
                  <Link key="view" to={`/jobs/${run.job_id}`}>
                    View Job
                  </Link>,
                ]}
              >
                <List.Item.Meta
                  avatar={<StatusBadge status={run.status} />}
                  title={
                    <Space>
                      <Typography.Text strong>{run.job_id}</Typography.Text>
                      {run.user && <Typography.Text type="secondary">by {run.user}</Typography.Text>}
                    </Space>
                  }
                  description={
                    <Space direction="vertical" size={0}>
                      <Typography.Text type="secondary">
                        Worker: {run.worker_id || "N/A"} · Exit Code: {run.returncode ?? "N/A"}
                      </Typography.Text>
                      <Typography.Text type="secondary">
                        {run.start_ts ? new Date(run.start_ts).toLocaleString() : "N/A"}
                      </Typography.Text>
                      {run.completion_reason && (
                        <Typography.Text type="danger" style={{ fontSize: 12 }}>
                          {run.completion_reason}
                        </Typography.Text>
                      )}
                    </Space>
                  }
                />
              </List.Item>
            )}
          />
        ) : (
          <Empty description="No failed jobs recently" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        )}
      </Card>
    </Space>
  );
}
