import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useQuery } from "@tanstack/react-query";
import { Card, Table, Tag, Progress, Tooltip } from "antd";
import { fetchWorkers } from "../api/jobs";
export function WorkersPanel() {
    const { data, isLoading } = useQuery({
        queryKey: ["workers"],
        queryFn: fetchWorkers,
        refetchInterval: 5000,
    });
    const columns = [
        { title: "ID", dataIndex: "worker_id", key: "worker_id" },
        { title: "OS", dataIndex: "os", key: "os" },
        { title: "Host", dataIndex: "hostname", key: "hostname" },
        { title: "IP", dataIndex: "ip", key: "ip" },
        { title: "Deploy", dataIndex: "deployment_type", key: "deployment_type" },
        { title: "State", dataIndex: "state", key: "state", render: (state) => _jsx(Tag, { children: state || "online" }) },
        {
            title: "Queues",
            dataIndex: "queues",
            key: "queues",
            render: (queues) => (queues?.length ? queues.join(", ") : "default"),
        },
        {
            title: "Tags",
            dataIndex: "tags",
            key: "tags",
            render: (tags) => (tags.length ? tags.map((tag) => _jsx(Tag, { children: tag }, tag)) : "-"),
        },
        {
            title: "Concurrency",
            key: "concurrency",
            render: (_, record) => (_jsx(Tooltip, { title: _jsxs(_Fragment, { children: [_jsxs("div", { children: ["CPU: ", record.cpu_count ?? "-"] }), _jsxs("div", { children: ["Python: ", record.python_version ?? "-"] }), _jsxs("div", { children: ["CWD: ", record.cwd ?? "-"] }), _jsxs("div", { children: ["User: ", record.run_user ?? "-"] }), _jsxs("div", { children: ["Subnet: ", record.subnet ?? "-"] })] }), children: _jsx(Progress, { size: "small", percent: Math.round((record.current_running / Math.max(record.max_concurrency, 1)) * 100), format: () => `${record.current_running}/${record.max_concurrency}` }) })),
        },
        {
            title: "Status",
            dataIndex: "status",
            key: "status",
            render: (status) => _jsx(Tag, { color: status === "online" ? "green" : "volcano", children: status }),
        },
        {
            title: "Running Jobs",
            dataIndex: "running_jobs",
            key: "running_jobs",
            render: (jobs) => (jobs?.length ? jobs.length : 0),
        },
    ];
    return (_jsx(Card, { title: "Workers", bordered: false, children: _jsx(Table, { size: "small", loading: isLoading, dataSource: (data ?? []).map((worker) => ({ ...worker, key: worker.worker_id })), columns: columns, pagination: false }) }));
}
