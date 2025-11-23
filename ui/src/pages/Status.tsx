import { useQuery } from "@tanstack/react-query";
import { Card, List, Space, Tag, Typography, Button, Progress } from "antd";
import { fetchJobOverview, runJobNow } from "../api/jobs";
import { useMutation, useQueryClient } from "@tanstack/react-query";

export function StatusPage() {
  const queryClient = useQueryClient();
  const overviewQuery = useQuery({ queryKey: ["job-overview"], queryFn: fetchJobOverview, refetchInterval: 5000 });

  const runNow = useMutation({
    mutationFn: (jobId: string) => runJobNow(jobId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["job-overview"] });
    },
  });

  return (
    <Card title="Status">
      <List
        loading={overviewQuery.isLoading}
        dataSource={overviewQuery.data ?? []}
        renderItem={(job) => {
          const last = job.last_run;
          return (
            <List.Item
              actions={[
                <Button key="run" size="small" onClick={() => runNow.mutate(job.job_id)} loading={runNow.isPending}>
                  Run Now
                </Button>,
              ]}
            >
              <List.Item.Meta
                title={
                  <Space>
                    <Typography.Text strong>{job.name}</Typography.Text>
                    <Tag>{job.schedule_mode}</Tag>
                    {last && <Tag color={last.status === "success" ? "green" : last.status === "running" ? "blue" : "volcano"}>{last.status}</Tag>}
                  </Space>
                }
                description={
                  <Space direction="vertical">
                    <div>Success: {job.success_runs} · Failed: {job.failed_runs} · Total: {job.total_runs}</div>
                    {last && (
                      <Space>
                        <div>Last run: {last.start_ts ? new Date(last.start_ts).toLocaleString() : "-"}</div>
                        {typeof last.duration === "number" && <div>Duration: {last.duration?.toFixed(1)}s</div>}
                      </Space>
                    )}
                    <Progress
                      percent={job.total_runs ? Math.round((job.success_runs / job.total_runs) * 100) : 0}
                      size="small"
                      status="active"
                    />
                  </Space>
                }
              />
            </List.Item>
          );
        }}
      />
    </Card>
  );
}
