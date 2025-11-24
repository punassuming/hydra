import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Card, Table, Tag } from "antd";
import { Link } from "react-router-dom";
export function JobList({ jobs, onSelect, selectedId, loading, onEdit }) {
    const dataSource = (jobs ?? []).map((job) => ({ ...job, key: job._id }));
    const columns = [
        {
            title: "Name",
            dataIndex: "name",
            key: "name",
            render: (_, record) => _jsx(Link, { to: `/jobs/${record._id}`, children: record.name }),
        },
        { title: "User", dataIndex: "user", key: "user" },
        {
            title: "Executor",
            key: "executor",
            render: (_, record) => _jsx(Tag, { color: "geekblue", children: record.executor.type }),
        },
        { title: "Queue", dataIndex: "queue", key: "queue" },
        { title: "Priority", dataIndex: "priority", key: "priority" },
        {
            title: "Schedule",
            key: "schedule",
            render: (_, record) => (_jsxs("div", { children: [_jsx("strong", { children: record.schedule.mode }), _jsx("br", {}), _jsx("small", { children: !record.schedule.enabled
                            ? "disabled"
                            : record.schedule.next_run_at
                                ? new Date(record.schedule.next_run_at).toLocaleString()
                                : record.schedule.mode === "immediate"
                                    ? "immediate"
                                    : "pending" })] })),
        },
        { title: "Retries", dataIndex: "retries", key: "retries" },
        {
            title: "Updated",
            dataIndex: "updated_at",
            key: "updated_at",
            render: (value) => new Date(value).toLocaleString(),
        },
    ];
    return (_jsx(Card, { title: "Jobs", bordered: false, children: _jsx(Table, { dataSource: dataSource, columns: columns, loading: loading, pagination: { pageSize: 10 }, size: "small", rowClassName: (record) => (record._id === selectedId ? "job-row-selected" : "job-row"), onRow: (record) => ({
                onClick: () => onSelect(record),
                onDoubleClick: () => {
                    onSelect(record);
                    onEdit?.();
                },
                style: { cursor: "pointer" },
            }) }) }));
}
