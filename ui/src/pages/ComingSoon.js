import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Card, Typography } from "antd";
export function ComingSoon({ title, description }) {
    return (_jsxs(Card, { children: [_jsx(Typography.Title, { level: 3, children: title }), _jsx(Typography.Paragraph, { children: description ?? "This section is under construction. Check back soon for full functionality." })] }));
}
