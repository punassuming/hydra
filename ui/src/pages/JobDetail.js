import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Card, Space, Typography, Tabs, Button, Tag, Descriptions, message } from "antd";
import { JobRuns } from "../components/JobRuns";
import { JobGridView } from "../components/JobGridView";
import { JobGanttView } from "../components/JobGanttView";
import { JobGraphView } from "../components/JobGraphView";
import { fetchJob, fetchJobRuns, runJobNow } from "../api/jobs";
export function JobDetailPage() {
    const { jobId } = useParams();
    const navigate = useNavigate();
    const queryClient = useQueryClient();
    const [messageApi, contextHolder] = message.useMessage();
    const jobQuery = useQuery({
        queryKey: ["job", jobId],
        queryFn: () => fetchJob(jobId),
        enabled: Boolean(jobId),
    });
    const runsQuery = useQuery({
        queryKey: ["job-runs", jobId],
        queryFn: () => fetchJobRuns(jobId),
        enabled: Boolean(jobId),
        refetchInterval: 5000,
    });
    const manualRun = useMutation({
        mutationFn: (id) => runJobNow(id),
        onSuccess: () => {
            messageApi.success("Run queued");
            queryClient.invalidateQueries({ queryKey: ["job-runs", jobId] });
            queryClient.invalidateQueries({ queryKey: ["job-grid", jobId] });
            queryClient.invalidateQueries({ queryKey: ["job-gantt", jobId] });
            queryClient.invalidateQueries({ queryKey: ["job-graph", jobId] });
        },
    });
    const job = jobQuery.data;
    const tabItems = useMemo(() => {
        if (!job)
            return [];
        return [
            {
                key: "overview",
                label: "Overview",
                children: (_jsxs(Descriptions, { bordered: true, column: 1, size: "small", children: [_jsx(Descriptions.Item, { label: "Job ID", children: job._id }), _jsx(Descriptions.Item, { label: "Name", children: job.name }), _jsx(Descriptions.Item, { label: "User", children: job.user }), _jsx(Descriptions.Item, { label: "Executor", children: job.executor.type }), _jsx(Descriptions.Item, { label: "Schedule Mode", children: job.schedule.mode }), _jsx(Descriptions.Item, { label: "Retries", children: job.retries }), _jsxs(Descriptions.Item, { label: "Timeout", children: [job.timeout, "s"] })] })),
            },
            {
                key: "grid",
                label: "Grid",
                children: jobId ? _jsx(JobGridView, { jobId: jobId }) : null,
            },
            {
                key: "runs",
                label: "Runs",
                children: _jsx(JobRuns, { jobId: jobId, runs: runsQuery.data ?? [], loading: runsQuery.isLoading }),
            },
            {
                key: "gantt",
                label: "Gantt",
                children: jobId ? _jsx(JobGanttView, { jobId: jobId }) : null,
            },
            {
                key: "graph",
                label: "Graph",
                children: jobId ? _jsx(JobGraphView, { jobId: jobId }) : null,
            },
            {
                key: "code",
                label: "Code",
                children: (_jsx(Typography.Paragraph, { style: { whiteSpace: "pre-wrap" }, children: job.executor.type === "python" ? job.executor.code : job.executor.type === "shell" ? job.executor.script : "No inline code" })),
            },
        ];
    }, [job, jobId, runsQuery.data, runsQuery.isLoading]);
    if (!jobId) {
        return _jsx(Typography.Text, { children: "Select a job from the jobs list." });
    }
    if (jobQuery.isLoading) {
        return _jsx(Typography.Text, { children: "Loading job\u2026" });
    }
    if (!job) {
        return _jsx(Typography.Text, { children: "Job not found." });
    }
    return (_jsxs(Space, { direction: "vertical", style: { width: "100%" }, size: "large", children: [contextHolder, _jsx(Card, { children: _jsxs(Space, { direction: "vertical", style: { width: "100%" }, children: [_jsxs(Space, { align: "center", wrap: true, children: [_jsx(Typography.Title, { level: 3, style: { marginBottom: 0 }, children: job.name }), _jsx(Tag, { color: "blue", children: job.executor.type }), _jsx(Tag, { color: job.schedule.enabled ? "green" : "default", children: job.schedule.mode })] }), _jsxs(Space, { children: [_jsx(Button, { onClick: () => manualRun.mutate(job._id), children: "Run Now" }), _jsx(Button, { onClick: () => navigate("/"), children: "Back to Jobs" })] })] }) }), _jsx(Tabs, { items: tabItems })] }));
}
