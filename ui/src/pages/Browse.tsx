import { useQuery } from "@tanstack/react-query";
import { Tabs, Card, Typography } from "antd";
import { fetchJobs, fetchHistory } from "../api/jobs";
import { JobList } from "../components/JobList";
import { JobRuns } from "../components/JobRuns";
import { useActiveDomain } from "../context/ActiveDomainContext";

export function BrowsePage() {
  const { domain } = useActiveDomain();
  const jobsQuery = useQuery({ queryKey: ["jobs", domain], queryFn: () => fetchJobs(), refetchInterval: 5000 });
  const historyQuery = useQuery({ queryKey: ["history", domain], queryFn: () => fetchHistory(), refetchInterval: 5000 });

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
          <JobRuns runs={historyQuery.data?.items ?? []} loading={historyQuery.isLoading} />
        </Card>
      ),
    },
  ];

  return <Tabs items={items} />;
}
