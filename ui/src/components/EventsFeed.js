import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Card, List, Tag, Typography, Space } from "antd";
export function EventsFeed({ events }) {
    return (_jsx(Card, { title: "Scheduler Events", bordered: false, children: events.length === 0 ? (_jsx(Typography.Text, { type: "secondary", children: "No recent events." })) : (_jsx(List, { dataSource: events, renderItem: (evt) => (_jsx(List.Item, { children: _jsxs(Space, { direction: "vertical", size: 0, children: [_jsx(Tag, { children: evt.type }), _jsx(Typography.Text, { type: "secondary", children: new Date(evt.ts * 1000).toLocaleTimeString() }), _jsx(Typography.Text, { code: true, children: JSON.stringify(evt.payload) })] }) }, `${evt.ts}-${evt.type}`)) })) }));
}
