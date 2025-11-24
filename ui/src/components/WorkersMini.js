import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Card, Col, Row, Space, Tag, Typography, Skeleton } from "antd";
import { useQuery } from "@tanstack/react-query";
import { fetchWorkers } from "../api/jobs";
import { Link } from "react-router-dom";
export function WorkersMini() {
    const { data, isLoading } = useQuery({ queryKey: ["workers"], queryFn: fetchWorkers, refetchInterval: 8000 });
    const workers = data ?? [];
    return (_jsx(Card, { title: _jsxs(Space, { children: [_jsx(Typography.Text, { strong: true, children: "Workers" }), _jsxs(Tag, { color: "geekblue", children: [workers.length, " online / ", _jsx(Link, { to: "/workers", children: "view all" })] })] }), bordered: false, children: isLoading ? (_jsx(Skeleton, { active: true, paragraph: { rows: 2 } })) : (_jsx(Row, { gutter: [12, 12], children: workers.slice(0, 4).map((w) => (_jsx(Col, { xs: 24, sm: 12, md: 12, lg: 12, children: _jsx(Card, { size: "small", bordered: true, style: { minHeight: 120 }, children: _jsxs(Space, { direction: "vertical", size: 4, children: [_jsxs(Space, { children: [_jsx(Typography.Text, { strong: true, children: w.worker_id }), _jsx(Tag, { color: w.status === "online" ? "green" : "volcano", children: w.status })] }), _jsx("div", { children: w.hostname || w.worker_id }), _jsxs("div", { children: ["Queues: ", (w.queues ?? ["default"]).join(", ")] }), _jsxs("div", { children: ["Running: ", w.current_running, "/", w.max_concurrency] }), _jsx(Link, { to: "/workers", children: "Details" })] }) }) }, w.worker_id))) })) }));
}
