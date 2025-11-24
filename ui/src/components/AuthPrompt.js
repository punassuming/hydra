import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Modal, Input, Typography, Space, message } from "antd";
import { useState } from "react";
import { setAuthToken } from "../api/client";
export function AuthPrompt({ open, onClose, onSuccess }) {
    const [token, setToken] = useState("");
    return (_jsx(Modal, { open: open, title: "Enter Access Token", onCancel: onClose, onOk: () => {
            if (!token.trim()) {
                message.error("Token required");
                return;
            }
            setAuthToken(token.trim());
            message.success("Token saved");
            onSuccess?.();
            onClose();
        }, okText: "Save", children: _jsxs(Space, { direction: "vertical", style: { width: "100%" }, children: [_jsx(Typography.Text, { children: "Enter your domain or admin token. It will be stored locally and used for all API calls." }), _jsx(Input.Password, { value: token, onChange: (e) => setToken(e.target.value), placeholder: "Token" })] }) }));
}
