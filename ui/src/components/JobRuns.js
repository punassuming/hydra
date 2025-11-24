import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useQuery } from "@tanstack/react-query";
import { Table, Tag, Modal, Typography, Space, Divider } from "antd";
import { fetchJobRuns } from "../api/jobs";
import { useEffect, useState } from "react";
import { runStreamUrl } from "../api/client";
import { Link } from "react-router-dom";
export function JobRuns({ jobId, runs: providedRuns, loading }) {
    const enabled = Boolean(jobId);
    const shouldQuery = !providedRuns && enabled;
    const { data, isLoading } = useQuery({
        queryKey: ["job-runs", jobId],
        queryFn: () => fetchJobRuns(jobId),
        enabled: shouldQuery,
        refetchInterval: shouldQuery ? 5000 : false,
    });
    const [logModal, setLogModal] = useState({ visible: false });
    const [liveLogs, setLiveLogs] = useState({ stdout: "", stderr: "" });
    const [source, setSource] = useState(null);
    useEffect(() => {
        if (!logModal.visible || !logModal.run) {
            source?.close();
            setSource(null);
            return;
        }
        const baseStdout = logModal.run.stdout_tail ?? logModal.run.stdout ?? "";
        const baseStderr = logModal.run.stderr_tail ?? logModal.run.stderr ?? "";
        setLiveLogs({ stdout: baseStdout, stderr: baseStderr });
        if (logModal.run.status !== "running") {
            return;
        }
        const es = new EventSource(runStreamUrl(logModal.run._id));
        es.onmessage = (evt) => {
            try {
                const payload = JSON.parse(evt.data);
                if (!payload?.text)
                    return;
                setLiveLogs((prev) => {
                    const key = payload.stream === "stderr" ? "stderr" : "stdout";
                    return { ...prev, [key]: prev[key] + payload.text };
                });
            }
            catch {
                // ignore
            }
        };
        es.onerror = () => {
            es.close();
            setSource(null);
        };
        setSource(es);
        return () => {
            es.close();
            setSource(null);
        };
    }, [logModal]);
    const columns = [
        {
            title: "Job",
            dataIndex: "job_id",
            key: "job_id",
            render: (value) => (value ? _jsx(Link, { to: `/jobs/${value}`, children: value.slice(0, 8) }) : "-"),
            hidden: Boolean(jobId),
        },
        {
            title: "Status",
            dataIndex: "status",
            key: "status",
            render: (status) => _jsx(Tag, { color: status === "success" ? "green" : status === "running" ? "blue" : "volcano", children: status }),
        },
        { title: "Worker", dataIndex: "worker_id", key: "worker_id" },
        { title: "Slot", dataIndex: "slot", key: "slot" },
        { title: "Attempt", dataIndex: "attempt", key: "attempt" },
        {
            title: "Queued (ms)",
            dataIndex: "queue_latency_ms",
            key: "queue_latency_ms",
            render: (value) => (value !== undefined ? value.toFixed(0) : "-"),
        },
        {
            title: "Queued At",
            dataIndex: "scheduled_ts",
            key: "scheduled_ts",
            render: (value) => (value ? new Date(value).toLocaleTimeString() : "-"),
        },
        {
            title: "Started",
            dataIndex: "start_ts",
            key: "start_ts",
            render: (value) => (value ? new Date(value).toLocaleTimeString() : "-"),
        },
        {
            title: "Finished",
            dataIndex: "end_ts",
            key: "end_ts",
            render: (value) => (value ? new Date(value).toLocaleTimeString() : "-"),
        },
        { title: "Reason", dataIndex: "completion_reason", key: "completion_reason" },
        {
            title: "",
            key: "logs",
            render: (_, record) => (_jsx(Typography.Link, { onClick: () => setLogModal({ visible: true, run: record }), children: "View Logs" })),
        },
    ];
    const combinedRuns = (providedRuns ?? data ?? []).map((run) => ({ ...run, key: run._id }));
    const tableLoading = typeof loading === "boolean" ? loading : isLoading;
    const visibleColumns = columns.filter((col) => !col.hidden);
    return (_jsxs(_Fragment, { children: [!jobId && !providedRuns ? (_jsx("p", { children: "Select a job to view run history." })) : (_jsx(Table, { dataSource: combinedRuns, columns: visibleColumns, loading: tableLoading, pagination: { pageSize: 10 }, size: "small" })), _jsx(Modal, { open: !!logModal?.visible, onCancel: () => setLogModal({ visible: false }), footer: null, width: 900, title: "Run Logs", children: logModal?.run ? (_jsxs(Space, { direction: "vertical", style: { width: "100%" }, children: [_jsxs(Space, { children: [_jsx(Tag, { color: logModal.run.status === "success" ? "green" : logModal.run.status === "running" ? "blue" : "volcano", children: logModal.run.status }), _jsxs(Typography.Text, { type: "secondary", children: ["Run ID: ", logModal.run._id] }), logModal.run.worker_id && _jsxs(Typography.Text, { type: "secondary", children: ["Worker: ", logModal.run.worker_id] })] }), _jsxs(Typography.Text, { children: ["Started: ", logModal.run.start_ts ? new Date(logModal.run.start_ts).toLocaleString() : "-", " \u00B7 Finished:", " ", logModal.run.end_ts ? new Date(logModal.run.end_ts).toLocaleString() : "-", " \u00B7 Duration:", " ", typeof logModal.run.duration === "number" ? `${logModal.run.duration.toFixed(1)}s` : "-"] }), _jsxs(Typography.Text, { children: ["Exit: ", logModal.run.returncode ?? "-", " \u00B7 Reason: ", logModal.run.completion_reason ?? "-", " \u00B7 Queue latency:", " ", logModal.run.queue_latency_ms ? `${logModal.run.queue_latency_ms.toFixed(0)}ms` : "-"] }), _jsx(Divider, {}), _jsxs(Typography.Paragraph, { children: [_jsx(Typography.Text, { strong: true, children: "Stdout:" }), _jsx("pre", { style: { background: "#f5f5f5", padding: 12, maxHeight: 240, overflow: "auto" }, children: liveLogs.stdout || "(no stdout)" }), _jsx(Typography.Text, { type: "secondary", children: "Showing tail of last 4KB." })] }), _jsxs(Typography.Paragraph, { children: [_jsx(Typography.Text, { strong: true, children: "Stderr:" }), _jsx("pre", { style: { background: "#f5f5f5", padding: 12, maxHeight: 240, overflow: "auto" }, children: liveLogs.stderr || "(no stderr)" })] })] })) : (_jsx(Typography.Text, { type: "secondary", children: "No logs available." })) })] }));
}
