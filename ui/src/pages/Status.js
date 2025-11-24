import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Card, Space, Tag, Typography, Button, Progress, Table, Row, Col } from "antd";
import { fetchJobOverview, fetchQueueOverview, runJobNow } from "../api/jobs";
export function StatusPage() {
    const queryClient = useQueryClient();
    const overviewQuery = useQuery({ queryKey: ["job-overview"], queryFn: fetchJobOverview, refetchInterval: 5000 });
    const queueQuery = useQuery({ queryKey: ["queue-overview"], queryFn: fetchQueueOverview, refetchInterval: 3000 });
    const runNow = useMutation({
        mutationFn: (jobId) => runJobNow(jobId),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["job-overview"] });
        },
    });
    const renderRunStrip = (runs) => {
        const recent = (runs ?? []).slice(0, 10);
        if (!recent.length)
            return _jsx(Typography.Text, { type: "secondary", children: "No runs yet" });
        const color = (status) => status === "success" ? "#16a34a" : status === "running" ? "#2563eb" : "#f97316";
        return (_jsx(Space, { size: 6, children: recent.map((run, idx) => (_jsx("div", { title: `${run.status} · ${run.start_ts ? new Date(run.start_ts).toLocaleString() : "n/a"}`, style: {
                    width: 12,
                    height: 12,
                    borderRadius: 3,
                    background: color(run.status),
                    opacity: idx === 0 ? 1 : 0.7,
                } }, run._id ?? idx))) }));
    };
    const renderDurationSpark = (runs) => {
        const durations = (runs ?? [])
            .map((r) => (typeof r.duration === "number" ? r.duration : null))
            .filter((d) => d !== null);
        if (!durations.length)
            return _jsx(Typography.Text, { type: "secondary", children: "No duration data" });
        const max = Math.max(...durations, 1);
        return (_jsx("div", { style: { display: "flex", alignItems: "flex-end", gap: 4, height: 40 }, children: durations.map((d, idx) => (_jsx("div", { style: {
                    width: 12,
                    height: Math.max(6, (d / max) * 36),
                    background: "#38bdf8",
                    borderRadius: 4,
                    opacity: 0.8,
                }, title: `~${d.toFixed(1)}s` }, `${d}-${idx}`))) }));
    };
    return (_jsxs(Space, { direction: "vertical", size: "large", style: { width: "100%" }, children: [_jsx(Card, { title: "Status", extra: _jsx(Typography.Text, { type: "secondary", children: "Status aggregates run health; jump to Jobs for configuration or Workers for placement." }), children: _jsx(Table, { rowKey: "job_id", loading: overviewQuery.isLoading, dataSource: overviewQuery.data ?? [], pagination: { pageSize: 8 }, columns: [
                        {
                            title: "Job",
                            dataIndex: "name",
                            key: "name",
                            render: (_, job) => {
                                const last = job.last_run;
                                return (_jsxs(Space, { children: [_jsx(Typography.Text, { strong: true, children: job.name }), _jsx(Tag, { children: job.schedule_mode }), last && (_jsx(Tag, { color: last.status === "success" ? "green" : last.status === "running" ? "blue" : "volcano", children: last.status }))] }));
                            },
                        },
                        {
                            title: "Success / Failed / Total / Queued",
                            key: "counts",
                            render: (_, job) => (_jsxs(Space, { direction: "vertical", size: 4, children: [_jsxs("div", { children: [job.success_runs, " / ", job.failed_runs, " / ", job.total_runs, " / ", job.queued_runs ?? 0] }), _jsx(Progress, { percent: job.total_runs ? Math.round((job.success_runs / job.total_runs) * 100) : 0, size: "small", status: "active" })] })),
                        },
                        {
                            title: "Recent Runs",
                            key: "recent",
                            render: (_, job) => renderRunStrip(job.recent_runs),
                        },
                        {
                            title: "Durations",
                            key: "durations",
                            render: (_, job) => renderDurationSpark(job.recent_runs),
                        },
                        {
                            title: "Last Run",
                            key: "last",
                            render: (_, job) => {
                                const last = job.last_run;
                                if (!last)
                                    return "-";
                                return (_jsxs(Space, { direction: "vertical", size: 2, children: [_jsx("div", { children: last.start_ts ? new Date(last.start_ts).toLocaleString() : "-" }), typeof last.duration === "number" && _jsxs("div", { children: [last.duration.toFixed(1), "s"] })] }));
                            },
                        },
                        {
                            title: "",
                            key: "actions",
                            render: (_, job) => (_jsx(Button, { size: "small", onClick: () => runNow.mutate(job.job_id), loading: runNow.isPending, children: "Run Now" })),
                        },
                    ] }) }), _jsxs(Row, { gutter: [16, 16], children: [_jsx(Col, { xs: 24, lg: 12, children: _jsx(Card, { title: "Queued Jobs", loading: queueQuery.isLoading, children: _jsx(Table, { rowKey: "job_id", size: "small", pagination: false, dataSource: queueQuery.data?.pending ?? [], columns: [
                                    { title: "Job", dataIndex: "name", key: "name" },
                                    { title: "Queue", dataIndex: "queue", key: "queue" },
                                    { title: "Priority", dataIndex: "priority", key: "priority" },
                                    { title: "User", dataIndex: "user", key: "user" },
                                ] }) }) }), _jsx(Col, { xs: 24, lg: 12, children: _jsx(Card, { title: "Upcoming (scheduled)", loading: queueQuery.isLoading, children: _jsx(Table, { rowKey: "job_id", size: "small", pagination: false, dataSource: queueQuery.data?.upcoming ?? [], columns: [
                                    { title: "Job", dataIndex: "name", key: "name" },
                                    { title: "Queue", dataIndex: "queue", key: "queue" },
                                    { title: "Priority", dataIndex: "priority", key: "priority" },
                                    {
                                        title: "Next Run",
                                        dataIndex: "next_run_at",
                                        key: "next_run_at",
                                        render: (v) => (v ? new Date(v).toLocaleString() : "-"),
                                    },
                                ] }) }) })] })] }));
}
