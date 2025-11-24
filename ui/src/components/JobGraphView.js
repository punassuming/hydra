import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useQuery } from "@tanstack/react-query";
import { Card, List, Tag } from "antd";
import { fetchJobGraph } from "../api/jobs";
export function JobGraphView({ jobId }) {
    const { data, isLoading } = useQuery({
        queryKey: ["job-graph", jobId],
        queryFn: () => fetchJobGraph(jobId),
        enabled: Boolean(jobId),
    });
    return (_jsxs(Card, { loading: isLoading, children: [_jsx(List, { header: "Nodes", dataSource: data?.nodes ?? [], renderItem: (node) => (_jsxs(List.Item, { children: [node.label, " ", _jsx(Tag, { style: { marginLeft: 8 }, children: node.status })] }, node.id)) }), data?.edges?.length ? (_jsx(List, { header: "Edges", dataSource: data.edges, renderItem: (edge, idx) => (_jsxs(List.Item, { children: [edge.source, " \u2192 ", edge.target] }, `${edge.source}-${edge.target}-${idx}`)) })) : (_jsx("p", { children: "No edges defined." }))] }));
}
