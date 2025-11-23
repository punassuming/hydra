import { useQuery } from "@tanstack/react-query";
import { Card, List, Tag } from "antd";
import { fetchJobGantt } from "../api/jobs";

interface Props {
  jobId: string;
}

export function JobGanttView({ jobId }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ["job-gantt", jobId],
    queryFn: () => fetchJobGantt(jobId),
    enabled: Boolean(jobId),
    refetchInterval: 5000,
  });

  return (
    <Card loading={isLoading}>
      <List
        dataSource={data?.entries ?? []}
        renderItem={(entry) => (
          <List.Item key={entry.run_id}>
            <List.Item.Meta
              title={
                <>
                  Run {entry.run_id} <Tag>{entry.status}</Tag>
                </>
              }
              description={`Start: ${entry.start_ts ?? "-"} | End: ${entry.end_ts ?? "-"} | Duration: ${
                entry.duration != null ? entry.duration.toFixed(1) : "-"
              }s`}
            />
          </List.Item>
        )}
      />
    </Card>
  );
}
