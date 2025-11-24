import { jsx as _jsx, Fragment as _Fragment, jsxs as _jsxs } from "react/jsx-runtime";
import { useQuery } from "@tanstack/react-query";
import { Card, List, Tag } from "antd";
import { fetchJobGantt } from "../api/jobs";
export function JobGanttView({ jobId }) {
    const { data, isLoading } = useQuery({
        queryKey: ["job-gantt", jobId],
        queryFn: () => fetchJobGantt(jobId),
        enabled: Boolean(jobId),
        refetchInterval: 5000,
    });
    return (_jsx(Card, { loading: isLoading, children: _jsx(List, { dataSource: data?.entries ?? [], renderItem: (entry) => (_jsx(List.Item, { children: _jsx(List.Item.Meta, { title: _jsxs(_Fragment, { children: ["Run ", entry.run_id, " ", _jsx(Tag, { children: entry.status })] }), description: `Start: ${entry.start_ts ?? "-"} | End: ${entry.end_ts ?? "-"} | Duration: ${entry.duration != null ? entry.duration.toFixed(1) : "-"}s` }) }, entry.run_id)) }) }));
}
