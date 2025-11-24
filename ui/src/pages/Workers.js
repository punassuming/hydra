import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Card, Col, Row, Space, Statistic, Table, Tag, Tooltip, Typography, Button } from "antd";
import { fetchWorkers } from "../api/jobs";
import { apiClient } from "../api/client";
import { useNavigate } from "react-router-dom";
export function WorkersPage() {
    const queryClient = useQueryClient();
    const { data, isLoading } = useQuery({ queryKey: ["workers"], queryFn: fetchWorkers, refetchInterval: 5000 });
    const navigate = useNavigate();
    const setStateMutation = useMutation({
        mutationFn: ({ workerId, state }) => apiClient.post(`/workers/${workerId}/state`, { state }),
        onSuccess: () => queryClient.invalidateQueries({ queryKey: ["workers"] }),
    });
    const columns = [
        { title: "ID", dataIndex: "worker_id", key: "worker_id" },
        { title: "Domain", dataIndex: "domain", key: "domain" },
        { title: "Host", dataIndex: "hostname", key: "hostname" },
        { title: "IP", dataIndex: "ip", key: "ip" },
        { title: "OS", dataIndex: "os", key: "os" },
        { title: "Deploy", dataIndex: "deployment_type", key: "deployment_type" },
        { title: "Subnet", dataIndex: "subnet", key: "subnet" },
        { title: "Queues", dataIndex: "queues", key: "queues", render: (qs) => (qs?.length ? qs.join(", ") : "default") },
        {
            title: "Tags",
            dataIndex: "tags",
            key: "tags",
            render: (tags) => (tags?.length ? tags.map((tag) => _jsx(Tag, { children: tag }, tag)) : "-"),
        },
        {
            title: "Affinity Users",
            dataIndex: "allowed_users",
            key: "allowed_users",
            render: (users) => (users?.length ? users.join(", ") : "any"),
        },
        {
            title: "Runtime",
            key: "runtime",
            render: (_, record) => (_jsxs(Space, { size: 4, direction: "vertical", children: [_jsxs("div", { children: ["Python: ", record.python_version ?? "-"] }), _jsxs("div", { children: ["CPU: ", record.cpu_count ?? "-"] }), _jsxs("div", { children: ["User: ", record.run_user ?? "-"] })] })),
        },
        {
            title: "Concurrency",
            key: "concurrency",
            render: (_, record) => (_jsx(Tooltip, { title: `Running ${record.current_running} of ${record.max_concurrency}`, children: _jsxs("div", { children: [record.current_running, "/", record.max_concurrency] }) })),
        },
        {
            title: "Last heartbeat",
            dataIndex: "last_heartbeat",
            key: "last_heartbeat",
            render: (value) => (value ? new Date(value).toLocaleTimeString() : "-"),
        },
        {
            title: "Status",
            dataIndex: "status",
            key: "status",
            render: (status) => _jsx(Tag, { color: status === "online" ? "green" : "volcano", children: status }),
        },
        {
            title: "State",
            key: "state",
            render: (_, record) => (_jsxs(Space, { children: [_jsx(Tag, { children: record.state ?? "online" }), _jsx(Button, { size: "small", onClick: () => setStateMutation.mutate({ workerId: record.worker_id, state: "online" }), children: "Online" }), _jsx(Button, { size: "small", onClick: () => setStateMutation.mutate({ workerId: record.worker_id, state: "draining" }), children: "Drain" }), _jsx(Button, { size: "small", danger: true, onClick: () => setStateMutation.mutate({ workerId: record.worker_id, state: "disabled" }), children: "Disable" })] })),
        },
        {
            title: "Running Jobs",
            dataIndex: "running_jobs",
            key: "running_jobs",
            render: (jobs) => (jobs?.length ? jobs.length : 0),
        },
    ];
    const workers = data ?? [];
    const online = workers.filter((w) => w.status === "online").length;
    const totalCapacity = workers.reduce((sum, w) => sum + (w.max_concurrency ?? 0), 0);
    const running = workers.reduce((sum, w) => sum + (w.current_running ?? 0), 0);
    return (_jsxs(Space, { direction: "vertical", size: "large", style: { width: "100%" }, children: [_jsx(Typography.Title, { level: 3, style: { marginBottom: 0 }, children: "Worker Capabilities" }), _jsx(Typography.Text, { type: "secondary", children: "Inspect deployments, advertised runtimes, and placement hints to design new affinities." }), _jsxs(Row, { gutter: 16, children: [_jsx(Col, { xs: 24, md: 8, children: _jsx(Card, { children: _jsx(Statistic, { title: "Workers Online", value: online, suffix: `/ ${workers.length}` }) }) }), _jsx(Col, { xs: 24, md: 8, children: _jsx(Card, { children: _jsx(Statistic, { title: "Running Tasks", value: running, suffix: `/ ${totalCapacity}` }) }) }), _jsx(Col, { xs: 24, md: 8, children: _jsx(Card, { children: _jsx(Statistic, { title: "Unique Tags", value: new Set(workers.flatMap((w) => w.tags ?? [])).size }) }) })] }), _jsx(Card, { children: _jsx(Table, { dataSource: workers.map((w) => ({ ...w, key: w.worker_id })), columns: columns, loading: isLoading, pagination: { pageSize: 10 }, size: "small", onRow: (record) => ({
                        onClick: () => navigate(`/workers/${record.worker_id}`),
                        style: { cursor: "pointer" },
                    }) }) })] }));
}
