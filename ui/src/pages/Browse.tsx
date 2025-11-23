import { useQuery } from "@tanstack/react-query";
import { Tabs, Card } from "antd";
import { fetchJobs, fetchHistory } from "../api/jobs";
import { JobList } from "../components/JobList";
import { JobRuns } from "../components/JobRuns";

export function BrowsePage() {
  const jobsQuery = useQuery({ queryKey: ["jobs"], queryFn: fetchJobs, refetchInterval: 5000 });
  const historyQuery = useQuery({ queryKey: ["history"], queryFn: fetchHistory, refetchInterval: 5000 });

  const items = [
    {
      key: "jobs",
      label: "Jobs",
      children: (
        <Card>
          <JobList jobs={jobsQuery.data ?? []} loading={jobsQuery.isLoading} onSelect={() => {}} />
        </Card>
      ),
    },
    {
      key: "runs",
      label: "Runs",
      children: (
        <Card>
          <JobRuns runs={historyQuery.data ?? []} loading={historyQuery.isLoading} />
        </Card>
      ),
    },
  ];

  return <Tabs items={items} />;
}
