import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Card, Form, Input, Space, Table, Typography, Button, message, Modal, Input as AntInput, Select } from "antd";
import { fetchDomains, createDomain, updateDomain } from "../api/admin";
import { setAuthToken, setDomain as storeDomain } from "../api/client";
import { createJob } from "../api/jobs";
import { useState } from "react";
export function AdminPage() {
    const queryClient = useQueryClient();
    const domainsQuery = useQuery({ queryKey: ["domains"], queryFn: fetchDomains, refetchInterval: 5000 });
    const [tokenModal, setTokenModal] = useState({ open: false });
    const [switchModal, setSwitchModal] = useState({ open: false });
    const [importText, setImportText] = useState("");
    const [importing, setImporting] = useState(false);
    const sampleOptions = [
        { key: "quick-shell", label: "Quick Shell", payload: {
                name: "quick-shell",
                user: "demo",
                affinity: { os: ["linux"], tags: [], allowed_users: [] },
                executor: { type: "shell", shell: "bash", script: "echo quick-ok" },
                retries: 0,
                timeout: 30,
                queue: "default",
                priority: 5,
                schedule: { mode: "immediate", enabled: true },
                completion: { exit_codes: [0], stdout_contains: ["quick-ok"], stdout_not_contains: [], stderr_contains: [], stderr_not_contains: [] },
            } },
        { key: "long-sleep", label: "Long Sleep", payload: {
                name: "long-sleep",
                user: "demo",
                affinity: { os: ["linux"], tags: [], allowed_users: [] },
                executor: { type: "shell", shell: "bash", script: "echo start; sleep 15; echo done" },
                retries: 0,
                timeout: 120,
                queue: "default",
                priority: 4,
                schedule: { mode: "immediate", enabled: true },
                completion: { exit_codes: [0], stdout_contains: ["done"], stdout_not_contains: ["error"], stderr_contains: [], stderr_not_contains: [] },
            } },
        { key: "python-env", label: "Python Env", payload: {
                name: "python-env",
                user: "demo",
                affinity: { os: ["linux"], tags: ["python"], allowed_users: [] },
                executor: {
                    type: "python",
                    interpreter: "python3",
                    code: "import sys; import platform; print('pyversion:', sys.version.split()[0]); print('platform:', platform.system())",
                    environment: { type: "system", python_version: "python3", requirements: [] },
                },
                retries: 0,
                timeout: 60,
                queue: "default",
                priority: 5,
                schedule: { mode: "immediate", enabled: true },
                completion: { exit_codes: [0], stdout_contains: ["pyversion:"], stdout_not_contains: [], stderr_contains: [], stderr_not_contains: [] },
            } },
        { key: "cron-ping", label: "Cron Ping", payload: {
                name: "cron-ping",
                user: "demo",
                affinity: { os: ["linux"], tags: [], allowed_users: [] },
                executor: { type: "shell", shell: "bash", script: "echo cron-run $(date +%s)" },
                retries: 0,
                timeout: 30,
                queue: "default",
                priority: 3,
                schedule: { mode: "cron", cron: "*/5 * * * *", enabled: true },
                completion: { exit_codes: [0], stdout_contains: ["cron-run"], stdout_not_contains: [], stderr_contains: [], stderr_not_contains: [] },
            } },
    ];
    const [selectedSample, setSelectedSample] = useState(undefined);
    const createMut = useMutation({
        mutationFn: createDomain,
        onSuccess: (data) => {
            message.success("Domain created");
            queryClient.invalidateQueries({ queryKey: ["domains"] });
            if (data?.token) {
                setTokenModal({ open: true, token: data.token, domain: data.domain });
            }
        },
        onError: (err) => message.error(err.message),
    });
    const updateMut = useMutation({
        mutationFn: ({ domain, payload }) => updateDomain(domain, payload),
        onSuccess: () => {
            message.success("Domain updated");
            queryClient.invalidateQueries({ queryKey: ["domains"] });
        },
        onError: (err) => message.error(err.message),
    });
    const columns = [
        { title: "Domain", dataIndex: "domain", key: "domain" },
        { title: "Display Name", dataIndex: "display_name", key: "display_name" },
        { title: "Description", dataIndex: "description", key: "description" },
        {
            title: "Actions",
            key: "actions",
            render: (_, record) => (_jsxs(Space, { children: [_jsx(Button, { size: "small", onClick: () => updateMut.mutate({ domain: record.domain, payload: { display_name: record.display_name || record.domain } }), children: "Save Name" }), _jsx(Button, { size: "small", type: "link", onClick: () => setSwitchModal({ open: true, domain: record.domain }), children: "Use Domain" })] })),
        },
    ];
    return (_jsxs(Space, { direction: "vertical", size: "large", style: { width: "100%" }, children: [_jsx(Typography.Title, { level: 3, style: { marginBottom: 0 }, children: "Admin \u2013 Domains" }), _jsx(Typography.Text, { type: "secondary", children: "Requires admin token. Manage domains and their metadata; update tokens and switch the UI session token when needed." }), _jsx(Card, { title: "Create Domain", children: _jsxs(Form, { layout: "vertical", onFinish: (values) => {
                        createMut.mutate(values);
                        if (values.token) {
                            setTokenModal({ open: true, token: values.token, domain: values.domain });
                        }
                    }, children: [_jsx(Form.Item, { name: "domain", label: "Domain", rules: [{ required: true }], children: _jsx(Input, { placeholder: "dev" }) }), _jsx(Form.Item, { name: "display_name", label: "Display Name", children: _jsx(Input, { placeholder: "Development" }) }), _jsx(Form.Item, { name: "description", label: "Description", children: _jsx(Input.TextArea, { rows: 2, placeholder: "Optional notes" }) }), _jsx(Form.Item, { name: "token", label: "Token (optional)", children: _jsx(Input, { placeholder: "Leave blank to auto-generate" }) }), _jsx(Button, { type: "primary", htmlType: "submit", loading: createMut.isPending, children: "Create" })] }) }), _jsx(Card, { title: "Domains", children: _jsx(Table, { dataSource: (domainsQuery.data?.domains ?? []).map((d) => ({ ...d, key: d.domain })), loading: domainsQuery.isLoading, columns: columns, pagination: false, size: "small" }) }), _jsx(Card, { title: "Import Jobs", children: _jsxs(Space, { direction: "vertical", style: { width: "100%" }, children: [_jsx(Typography.Text, { type: "secondary", children: "Paste a job JSON (single object or array) or use the sample set." }), _jsxs(Space, { children: [_jsx(Select, { placeholder: "Pick a sample job", style: { minWidth: 200 }, value: selectedSample, onChange: (val) => {
                                        setSelectedSample(val);
                                        const sample = sampleOptions.find((s) => s.key === val);
                                        if (sample) {
                                            setImportText(JSON.stringify(sample.payload, null, 2));
                                        }
                                    }, options: sampleOptions.map((s) => ({ label: s.label, value: s.key })) }), _jsx(Button, { onClick: () => {
                                        setImportText(JSON.stringify(sampleOptions.map((s) => s.payload), null, 2));
                                    }, children: "Load All Samples" })] }), _jsx(AntInput.TextArea, { rows: 6, placeholder: "[{...job1...}, {...job2...}]", value: importText, onChange: (e) => setImportText(e.target.value) }), _jsxs(Space, { children: [_jsx(Button, { onClick: async () => {
                                        const samples = [
                                            {
                                                name: "quick-shell",
                                                user: "demo",
                                                affinity: { os: ["linux"], tags: [], allowed_users: [] },
                                                executor: { type: "shell", shell: "bash", script: "echo quick-ok" },
                                                retries: 0,
                                                timeout: 30,
                                                queue: "default",
                                                priority: 5,
                                                schedule: { mode: "immediate", enabled: true },
                                                completion: { exit_codes: [0], stdout_contains: ["quick-ok"], stdout_not_contains: [], stderr_contains: [], stderr_not_contains: [] },
                                            },
                                            {
                                                name: "long-sleep",
                                                user: "demo",
                                                affinity: { os: ["linux"], tags: [], allowed_users: [] },
                                                executor: { type: "shell", shell: "bash", script: "echo start; sleep 15; echo done" },
                                                retries: 0,
                                                timeout: 120,
                                                queue: "default",
                                                priority: 4,
                                                schedule: { mode: "immediate", enabled: true },
                                                completion: { exit_codes: [0], stdout_contains: ["done"], stdout_not_contains: ["error"], stderr_contains: [], stderr_not_contains: [] },
                                            },
                                            {
                                                name: "python-env",
                                                user: "demo",
                                                affinity: { os: ["linux"], tags: ["python"], allowed_users: [] },
                                                executor: {
                                                    type: "python",
                                                    interpreter: "python3",
                                                    code: "import sys; import platform; print('pyversion:', sys.version.split()[0]); print('platform:', platform.system())",
                                                    environment: { type: "system", python_version: "python3", requirements: [] },
                                                },
                                                retries: 0,
                                                timeout: 60,
                                                queue: "default",
                                                priority: 5,
                                                schedule: { mode: "immediate", enabled: true },
                                                completion: { exit_codes: [0], stdout_contains: ["pyversion:"], stdout_not_contains: [], stderr_contains: [], stderr_not_contains: [] },
                                            },
                                            {
                                                name: "cron-ping",
                                                user: "demo",
                                                affinity: { os: ["linux"], tags: [], allowed_users: [] },
                                                executor: { type: "shell", shell: "bash", script: "echo cron-run $(date +%s)" },
                                                retries: 0,
                                                timeout: 30,
                                                queue: "default",
                                                priority: 3,
                                                schedule: { mode: "cron", cron: "*/5 * * * *", enabled: true },
                                                completion: { exit_codes: [0], stdout_contains: ["cron-run"], stdout_not_contains: [], stderr_contains: [], stderr_not_contains: [] },
                                            },
                                        ];
                                        setImportText(JSON.stringify(samples, null, 2));
                                    }, children: "Load Sample Set" }), _jsx(Button, { type: "primary", loading: importing, onClick: async () => {
                                        let jobs = [];
                                        try {
                                            const parsed = JSON.parse(importText);
                                            jobs = Array.isArray(parsed) ? parsed : [parsed];
                                        }
                                        catch (err) {
                                            message.error("Invalid JSON");
                                            return;
                                        }
                                        setImporting(true);
                                        const results = await Promise.allSettled(jobs.map((j) => createJob(j)));
                                        const ok = results.filter((r) => r.status === "fulfilled").length;
                                        const fail = results.length - ok;
                                        if (ok)
                                            message.success(`Imported ${ok} job(s)`);
                                        if (fail)
                                            message.error(`${fail} job(s) failed`);
                                        queryClient.invalidateQueries({ queryKey: ["jobs"] });
                                        setImporting(false);
                                    }, children: "Import" })] })] }) }), _jsx(Modal, { open: tokenModal.open, footer: null, onCancel: () => setTokenModal({ open: false }), title: `Domain Token – ${tokenModal.domain}`, children: _jsxs(Space, { direction: "vertical", style: { width: "100%" }, children: [_jsx(Typography.Text, { strong: true, children: "Copy this token for workers and client access:" }), _jsx(Typography.Paragraph, { code: true, children: tokenModal.token ?? "(no token provided)" })] }) }), _jsx(Modal, { open: switchModal.open, onCancel: () => setSwitchModal({ open: false }), onOk: () => {
                    if (!switchModal.token || !switchModal.domain) {
                        message.error("Enter a token");
                        return;
                    }
                    setAuthToken(switchModal.token);
                    storeDomain(switchModal.domain);
                    message.success(`Switched to domain ${switchModal.domain}`);
                    setSwitchModal({ open: false });
                }, title: `Activate domain ${switchModal.domain ?? ""}`, children: _jsxs(Space, { direction: "vertical", style: { width: "100%" }, children: [_jsx(Typography.Text, { strong: true, children: "Enter the domain token (workers use this token too). The UI will start using this token immediately." }), _jsx(Input.Password, { value: switchModal.token, onChange: (e) => setSwitchModal((prev) => ({ ...prev, token: e.target.value })), placeholder: "Domain token" })] }) })] }));
}
