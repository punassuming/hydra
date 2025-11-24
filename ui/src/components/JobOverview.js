import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchJobOverview } from "../api/jobs";
import { Card, Table, Tag, Modal, Typography, Space } from "antd";
import { Link } from "react-router-dom";
export function JobOverview() {
    const { data, isLoading } = useQuery({
        queryKey: ["job-overview"],
        queryFn: fetchJobOverview,
        refetchInterval: 5000,
    });
    const [logModal, setLogModal] = useState({
        visible: false,
    });
    const rows = useMemo(() => (data ?? []).map((item) => ({ ...item, key: item.job_id })), [data]);
    const columns = [
        {
            title: "Job",
            dataIndex: "name",
            key: "name",
            render: (_, record) => _jsx(Link, { to: `/jobs/${record.job_id}`, children: record.name }),
        },
        {
            title: "Schedule",
            dataIndex: "schedule_mode",
            key: "schedule_mode",
            render: (mode) => _jsx(Tag, { children: mode }),
        },
        { title: "Total Runs", dataIndex: "total_runs", key: "total_runs" },
        {
            title: "Success",
            dataIndex: "success_runs",
            key: "success_runs",
            render: (value, record) => (_jsx(Typography.Text, { type: value > 0 ? "success" : undefined, children: value })),
        },
        {
            title: "Failed",
            dataIndex: "failed_runs",
            key: "failed_runs",
            render: (value) => _jsx(Typography.Text, { type: value > 0 ? "danger" : undefined, children: value }),
        },
        { title: "Queued", dataIndex: "queued_runs", key: "queued_runs" },
        {
            title: "Last Run",
            key: "last_run",
            render: (_, record) => record.last_run ? new Date(record.last_run.start_ts || record.last_run.scheduled_ts || "").toLocaleString() : "-",
        },
        {
            title: "",
            key: "actions",
            render: (_, record) => (_jsx(Typography.Link, { onClick: () => setLogModal({
                    visible: true,
                    run: record.last_run,
                    jobName: record.name,
                }), disabled: !record.last_run, children: "View Logs" })),
        },
    ];
    return (_jsxs(_Fragment, { children: [_jsx(Card, { title: "Job Overview", bordered: false, children: _jsx(Table, { dataSource: rows, columns: columns, loading: isLoading, pagination: { pageSize: 10 }, size: "small" }) }), _jsx(Modal, { open: logModal.visible, title: `Logs - ${logModal.jobName ?? ""}`, onCancel: () => setLogModal({ visible: false }), footer: null, width: 800, children: logModal.run ? (_jsxs(Space, { direction: "vertical", style: { width: "100%" }, children: [_jsxs(Typography.Text, { strong: true, children: ["Status: ", logModal.run.status] }), _jsxs(Typography.Paragraph, { children: [_jsx(Typography.Text, { strong: true, children: "Stdout:" }), _jsxs("pre", { style: { background: "#f5f5f5", padding: 12 }, children: [logModal.run.stdout_tail ?? logModal.run.stdout ?? "(no stdout)", " "] })] }), _jsxs(Typography.Paragraph, { children: [_jsx(Typography.Text, { strong: true, children: "Stderr:" }), _jsx("pre", { style: { background: "#f5f5f5", padding: 12 }, children: logModal.run.stderr_tail ?? logModal.run.stderr ?? "(no stderr)" })] })] })) : (_jsx(Typography.Text, { type: "secondary", children: "No logs available." })) })] }));
}
