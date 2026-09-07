import { useMemo, useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { Table, Typography, Card } from "antd";
import { fetchHistory } from "../api/jobs";
import { JobRun } from "../types";
import { useActiveDomain } from "../context/ActiveDomainContext";
import { StatusBadge } from "../components/StatusBadge";
import { RunInspector } from "../components/RunInspector";
import { InfiniteScrollSentinel } from "../components/InfiniteScrollSentinel";

export function HistoryPage() {
  const { domain } = useActiveDomain();
  const { data, isLoading, fetchNextPage, hasNextPage, isFetchingNextPage } = useInfiniteQuery({
    queryKey: ["history", domain],
    queryFn: ({ pageParam }) => fetchHistory(pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => (lastPage.has_more ? (lastPage.next_cursor ?? undefined) : undefined),
    refetchInterval: 5000,
  });
  const [inspectedRun, setInspectedRun] = useState<JobRun | undefined>(undefined);

  const columns = [
    { title: "Job", dataIndex: "job_id", key: "job_id" },
    { title: "User", dataIndex: "user", key: "user" },
    { title: "Domain", dataIndex: "domain", key: "domain", render: (value?: string) => value ?? "prod" },
    {
      title: "Status",
      dataIndex: "status",
      key: "status",
      render: (status: string) => <StatusBadge status={status} />,
    },
    { title: "Worker", dataIndex: "worker_id", key: "worker_id" },
    {
      title: "Started",
      dataIndex: "start_ts",
      key: "start_ts",
      render: (value?: string) => (value ? new Date(value).toLocaleString() : "-"),
    },
    {
      title: "Finished",
      dataIndex: "end_ts",
      key: "end_ts",
      render: (value?: string) => (value ? new Date(value).toLocaleString() : "-"),
    },
    {
      title: "Logs",
      key: "logs",
      render: (_: unknown, record: JobRun) => (
        <Typography.Link onClick={() => setInspectedRun(record)}>View Logs</Typography.Link>
      ),
    },
  ];

  const runs = useMemo(
    () => (data?.pages ?? []).flatMap((page) => page.items).map((run) => ({ ...run, key: run._id })),
    [data],
  );

  return (
    <Card
      title="Job History"
      extra={<Typography.Text type="secondary">All runs across jobs. Open a run for logs; go to Jobs to edit definitions.</Typography.Text>}
    >
      <Table dataSource={runs} columns={columns} loading={isLoading} size="small" pagination={false} />
      <InfiniteScrollSentinel
        onIntersect={() => fetchNextPage()}
        enabled={Boolean(hasNextPage)}
        loading={isFetchingNextPage}
      />
      <RunInspector run={inspectedRun} open={Boolean(inspectedRun)} onClose={() => setInspectedRun(undefined)} />
    </Card>
  );
}
