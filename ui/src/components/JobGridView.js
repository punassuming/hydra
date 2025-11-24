import { jsx as _jsx } from "react/jsx-runtime";
import { useQuery } from "@tanstack/react-query";
import { Card, Table, Tag } from "antd";
import { fetchJobGrid } from "../api/jobs";
export function JobGridView({ jobId }) {
    const { data, isLoading } = useQuery({
        queryKey: ["job-grid", jobId],
        queryFn: () => fetchJobGrid(jobId),
        enabled: Boolean(jobId),
        refetchInterval: 5000,
    });
    const columns = [
        { title: "Run ID", dataIndex: "run_id", key: "run_id" },
        {
            title: "Status",
            dataIndex: "status",
            key: "status",
            render: (status) => _jsx(Tag, { color: status === "success" ? "green" : status === "running" ? "blue" : "volcano", children: status }),
        },
        { title: "Start", dataIndex: "start_ts", key: "start_ts" },
        { title: "End", dataIndex: "end_ts", key: "end_ts" },
        {
            title: "Duration (s)",
            dataIndex: "duration",
            key: "duration",
            render: (value) => (value != null ? value.toFixed(1) : "-"),
        },
    ];
    return (_jsx(Card, { children: _jsx(Table, { dataSource: (data?.runs ?? []).map((run) => ({ ...run, key: run.run_id })), columns: columns, loading: isLoading, pagination: false }) }));
}
