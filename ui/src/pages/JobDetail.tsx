import { useMemo, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Card, Space, Typography, Tabs, Button, Tag, Descriptions, message } from "antd";
import { JobRuns } from "../components/JobRuns";
import { fetchJob, fetchJobRuns, runJobNow } from "../api/jobs";

export function JobDetailPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const queryClient = useQueryClient();
  const [messageApi, contextHolder] = message.useMessage();

  const jobQuery = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => fetchJob(jobId!),
    enabled: Boolean(jobId),
  });

  const runsQuery = useQuery({
    queryKey: ["job-runs", jobId],
    queryFn: () => fetchJobRuns(jobId!),
    enabled: Boolean(jobId),
    refetchInterval: 5000,
  });

  const manualRun = useMutation({
    mutationFn: (id: string) => runJobNow(id),
    onSuccess: () => {
      messageApi.success("Run queued");
      queryClient.invalidateQueries({ queryKey: ["job-runs", jobId] });
    },
  });

  const job = jobQuery.data;

  const tabItems = useMemo(() => {
    if (!job) return [];
    return [
      {
        key: "overview",
        label: "Overview",
        children: (
          <Descriptions bordered column={1} size="small">
            <Descriptions.Item label="Job ID">{job._id}</Descriptions.Item>
            <Descriptions.Item label="Name">{job.name}</Descriptions.Item>
            <Descriptions.Item label="User">{job.user}</Descriptions.Item>
            <Descriptions.Item label="Executor">{job.executor.type}</Descriptions.Item>
            <Descriptions.Item label="Schedule Mode">{job.schedule.mode}</Descriptions.Item>
            <Descriptions.Item label="Retries">{job.retries}</Descriptions.Item>
            <Descriptions.Item label="Timeout">{job.timeout}s</Descriptions.Item>
          </Descriptions>
        ),
      },
      {
        key: "runs",
        label: "Runs",
        children: <JobRuns jobId={jobId} runs={runsQuery.data ?? []} loading={runsQuery.isLoading} />,
      },
      {
        key: "code",
        label: "Code",
        children: (
          <Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>
            {job.executor.type === "python" ? job.executor.code : job.executor.type === "shell" ? job.executor.script : "No inline code"}
          </Typography.Paragraph>
        ),
      },
    ];
  }, [job, jobId, runsQuery.data, runsQuery.isLoading]);

  if (!jobId) {
    return <Typography.Text>Select a job from the jobs list.</Typography.Text>;
  }

  if (jobQuery.isLoading) {
    return <Typography.Text>Loading job…</Typography.Text>;
  }

  if (!job) {
    return <Typography.Text>Job not found.</Typography.Text>;
  }

  return (
    <Space direction="vertical" style={{ width: "100%" }} size="large">
      {contextHolder}
      <Card>
        <Space direction="vertical" style={{ width: "100%" }}>
          <Space align="center" wrap>
            <Typography.Title level={3} style={{ marginBottom: 0 }}>
              {job.name}
            </Typography.Title>
            <Tag color="blue">{job.executor.type}</Tag>
            <Tag color={job.schedule.enabled ? "green" : "default"}>{job.schedule.mode}</Tag>
          </Space>
          <Space>
            <Button onClick={() => manualRun.mutate(job._id)}>
              Run Now
            </Button>
            <Button>
              <Link to="/">Back to Jobs</Link>
            </Button>
          </Space>
        </Space>
      </Card>
      <Tabs items={tabItems} />
    </Space>
  );
}
