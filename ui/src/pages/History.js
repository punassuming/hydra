import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Table, Tag, Modal, Typography, Space, Card } from "antd";
import { fetchHistory } from "../api/jobs";
export function HistoryPage() {
    const { data, isLoading } = useQuery({
        queryKey: ["history"],
        queryFn: fetchHistory,
        refetchInterval: 5000,
    });
    const [logModal, setLogModal] = useState({ visible: false });
    const columns = [
        { title: "Job", dataIndex: "job_id", key: "job_id" },
        { title: "User", dataIndex: "user", key: "user" },
        {
            title: "Status",
            dataIndex: "status",
            key: "status",
            render: (status) => _jsx(Tag, { color: status === "success" ? "green" : status === "running" ? "blue" : "volcano", children: status }),
        },
        { title: "Worker", dataIndex: "worker_id", key: "worker_id" },
        {
            title: "Started",
            dataIndex: "start_ts",
            key: "start_ts",
            render: (value) => (value ? new Date(value).toLocaleString() : "-"),
        },
        {
            title: "Finished",
            dataIndex: "end_ts",
            key: "end_ts",
            render: (value) => (value ? new Date(value).toLocaleString() : "-"),
        },
        {
            title: "Logs",
            key: "logs",
            render: (_, record) => (_jsx(Typography.Link, { onClick: () => setLogModal({ visible: true, run: record }), children: "View Logs" })),
        },
    ];
    const runs = (data ?? []).map((run) => ({ ...run, key: run._id }));
    return (_jsxs(Card, { title: "Job History", extra: _jsx(Typography.Text, { type: "secondary", children: "All runs across jobs. Open a run for logs; go to Jobs to edit definitions." }), children: [_jsx(Table, { dataSource: runs, columns: columns, loading: isLoading, size: "small", pagination: { pageSize: 10 } }), _jsx(Modal, { open: logModal.visible, onCancel: () => setLogModal({ visible: false }), footer: null, width: 800, title: "Run Logs", children: logModal.run ? (_jsxs(Space, { direction: "vertical", style: { width: "100%" }, children: [_jsxs(Typography.Text, { strong: true, children: ["Status: ", logModal.run.status] }), _jsxs(Typography.Paragraph, { children: [_jsx(Typography.Text, { strong: true, children: "Stdout:" }), _jsx("pre", { style: { background: "#f5f5f5", padding: 12, maxHeight: 200, overflow: "auto" }, children: logModal.run.stdout_tail ?? logModal.run.stdout ?? "(no stdout)" })] }), _jsxs(Typography.Paragraph, { children: [_jsx(Typography.Text, { strong: true, children: "Stderr:" }), _jsx("pre", { style: { background: "#f5f5f5", padding: 12, maxHeight: 200, overflow: "auto" }, children: logModal.run.stderr_tail ?? logModal.run.stderr ?? "(no stderr)" })] })] })) : (_jsx(Typography.Text, { type: "secondary", children: "No logs available." })) })] }));
}
