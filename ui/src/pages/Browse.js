import { jsx as _jsx } from "react/jsx-runtime";
import { useQuery } from "@tanstack/react-query";
import { Tabs, Card, Typography } from "antd";
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
            children: (_jsx(Card, { title: "Jobs", extra: _jsx(Typography.Text, { type: "secondary", children: "Manage and inspect job definitions; double-click to edit." }), children: _jsx(JobList, { jobs: jobsQuery.data ?? [], loading: jobsQuery.isLoading, onSelect: () => { } }) })),
        },
        {
            key: "runs",
            label: "Runs",
            children: (_jsx(Card, { title: "Runs", extra: _jsx(Typography.Text, { type: "secondary", children: "Recent runs across all jobs. Click logs to inspect output." }), children: _jsx(JobRuns, { runs: historyQuery.data ?? [], loading: historyQuery.isLoading }) })),
        },
    ];
    return _jsx(Tabs, { items: items });
}
