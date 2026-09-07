import { useMemo } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Tabs, Card, Typography } from "antd";
import { fetchJobs, fetchHistory } from "../api/jobs";
import { JobList } from "../components/JobList";
import { JobRuns } from "../components/JobRuns";
import { InfiniteScrollSentinel } from "../components/InfiniteScrollSentinel";
import { useActiveDomain } from "../context/ActiveDomainContext";

export function BrowsePage() {
  const { domain } = useActiveDomain();
  const jobsQuery = useQuery({ queryKey: ["jobs", domain], queryFn: () => fetchJobs(), refetchInterval: 5000 });
  const historyQuery = useInfiniteQuery({
    queryKey: ["history", domain],
    queryFn: ({ pageParam }) => fetchHistory(pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => (lastPage.has_more ? (lastPage.next_cursor ?? undefined) : undefined),
    refetchInterval: 5000,
  });
  const runs = useMemo(() => (historyQuery.data?.pages ?? []).flatMap((page) => page.items), [historyQuery.data]);

  const items = [
    {
      key: "jobs",
      label: "Jobs",
      children: (
        <Card
          title="Jobs"
          extra={<Typography.Text type="secondary">Manage and inspect job definitions; double-click to edit.</Typography.Text>}
        >
          <JobList jobs={jobsQuery.data ?? []} loading={jobsQuery.isLoading} onSelect={() => {}} />
        </Card>
      ),
    },
    {
      key: "runs",
      label: "Runs",
      children: (
        <Card
          title="Runs"
          extra={<Typography.Text type="secondary">Recent runs across all jobs. Click logs to inspect output.</Typography.Text>}
        >
          <JobRuns runs={runs} loading={historyQuery.isLoading} />
          <InfiniteScrollSentinel
            onIntersect={() => historyQuery.fetchNextPage()}
            enabled={Boolean(historyQuery.hasNextPage)}
            loading={historyQuery.isFetchingNextPage}
          />
        </Card>
      ),
    },
  ];

  return <Tabs items={items} />;
}
