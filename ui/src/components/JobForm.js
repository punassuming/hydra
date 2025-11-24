import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Collapse, Col, Divider, Form, Input, InputNumber, Row, Select, Space, Switch, Typography, } from "antd";
import { fetchWorkers } from "../api/jobs";
const defaultAffinity = {
    os: ["linux"],
    tags: [],
    allowed_users: [],
    hostnames: [],
    subnets: [],
    deployment_types: [],
};
const createDefaultPythonEnvironment = () => ({
    type: "system",
    python_version: "python3",
    requirements: [],
    requirements_file: null,
    venv_path: null,
});
const createDefaultPythonExecutor = () => ({
    type: "python",
    code: "# Add your Python here\nprint('hello')",
    interpreter: "python3",
    environment: createDefaultPythonEnvironment(),
});
const createDefaultPayload = () => ({
    name: "",
    user: "",
    queue: "default",
    priority: 5,
    affinity: {
        os: [...defaultAffinity.os],
        tags: [],
        allowed_users: [],
        hostnames: [],
        subnets: [],
        deployment_types: [],
    },
    executor: { type: "shell", script: "echo 'hello world'", shell: "bash" },
    retries: 0,
    timeout: 30,
    schedule: {
        mode: "immediate",
        enabled: true,
        cron: "",
        interval_seconds: 300,
        start_at: null,
        end_at: null,
        next_run_at: null,
        timezone: "UTC",
    },
    completion: {
        exit_codes: [0],
        stdout_contains: [],
        stdout_not_contains: [],
        stderr_contains: [],
        stderr_not_contains: [],
    },
});
export function JobForm({ selectedJob, onSubmit, onValidate, onManualRun, onAdhocRun, submitting, validating, statusMessage, onReset, }) {
    const [payload, setPayload] = useState(() => createDefaultPayload());
    const workersQuery = useQuery({
        queryKey: ["workers"],
        queryFn: fetchWorkers,
        staleTime: 5000,
    });
    const workerHints = useMemo(() => {
        const workers = workersQuery.data ?? [];
        const collect = (getter) => {
            const values = workers.flatMap((w) => {
                const v = getter(w);
                if (!v)
                    return [];
                return Array.isArray(v) ? v : [v];
            });
            return Array.from(new Set(values.filter(Boolean)));
        };
        return {
            os: collect((w) => w.os),
            tags: collect((w) => w.tags),
            users: collect((w) => w.allowed_users),
            hostnames: collect((w) => w.hostname),
            subnets: collect((w) => w.subnet),
            deployments: collect((w) => w.deployment_type),
            pythonVersions: collect((w) => w.python_version),
            queues: collect((w) => w.queues),
        };
    }, [workersQuery.data]);
    const normalizeExecutor = (exec) => {
        if (exec.type !== "python") {
            return exec;
        }
        return {
            ...exec,
            environment: {
                ...createDefaultPythonEnvironment(),
                python_version: exec.environment?.python_version ?? exec.interpreter ?? "python3",
                ...exec.environment,
                requirements: exec.environment?.requirements ?? [],
            },
        };
    };
    useEffect(() => {
        if (selectedJob) {
            setPayload({
                name: selectedJob.name,
                user: selectedJob.user,
                affinity: { ...createDefaultPayload().affinity, ...selectedJob.affinity },
                executor: normalizeExecutor(selectedJob.executor),
                retries: selectedJob.retries,
                timeout: selectedJob.timeout,
                queue: selectedJob.queue ?? "default",
                priority: selectedJob.priority ?? 5,
                schedule: { ...createDefaultPayload().schedule, ...(selectedJob.schedule ?? {}) },
                completion: { ...createDefaultPayload().completion, ...(selectedJob.completion ?? {}) },
            });
        }
        else {
            setPayload(createDefaultPayload());
        }
    }, [selectedJob]);
    const executor = payload.executor;
    const executorType = executor.type;
    const schedule = payload.schedule;
    const completion = payload.completion;
    const pythonEnv = executor.type === "python"
        ? { ...createDefaultPythonEnvironment(), ...executor.environment }
        : null;
    const updatePayload = (field, value) => {
        setPayload((prev) => ({ ...prev, [field]: value }));
    };
    const updateExecutor = (update) => {
        setPayload((prev) => ({ ...prev, executor: { ...prev.executor, ...update } }));
    };
    const updateSchedule = (update) => {
        setPayload((prev) => ({ ...prev, schedule: { ...prev.schedule, ...update } }));
    };
    const updateCompletion = (update) => {
        setPayload((prev) => ({ ...prev, completion: { ...prev.completion, ...update } }));
    };
    const updatePythonEnv = (update) => {
        if (executor.type !== "python") {
            return;
        }
        const merged = {
            ...createDefaultPythonEnvironment(),
            ...executor.environment,
            ...update,
        };
        updateExecutor({ environment: merged });
    };
    const updateAffinity = (key, value) => {
        updatePayload("affinity", {
            ...payload.affinity,
            [key]: value,
        });
    };
    const parseList = (value) => value
        .split(/\n|,/)
        .map((s) => s.trim())
        .filter(Boolean);
    const setCompletionList = (field, value) => {
        updateCompletion({ [field]: parseList(value) });
    };
    const toInputValue = (iso) => (iso ? new Date(iso).toISOString().slice(0, 16) : "");
    const fromInputValue = (value) => (value ? new Date(value).toISOString() : null);
    const handleSubmit = () => {
        const normalized = { ...payload, user: payload.user?.trim() || "default" };
        onSubmit(normalized);
    };
    const handleValidate = () => onValidate(payload);
    const executorTypeSelect = (_jsx(Form.Item, { label: "Executor Type", required: true, children: _jsx(Select, { value: executorType, onChange: (nextType) => {
                const defaults = {
                    python: createDefaultPythonExecutor(),
                    shell: { type: "shell", script: "echo 'hello world'", shell: "bash" },
                    batch: { type: "batch", script: "echo hello", shell: "cmd" },
                    external: { type: "external", command: "/usr/bin/env" },
                };
                updateExecutor(defaults[nextType]);
            }, options: [
                { label: "Shell", value: "shell" },
                { label: "Batch", value: "batch" },
                { label: "Python", value: "python" },
                { label: "External Binary", value: "external" },
            ] }) }));
    return (_jsxs(Form, { layout: "vertical", onFinish: handleSubmit, children: [_jsx(Collapse, { defaultActiveKey: ["basics", "executor", "schedule"], items: [
                    {
                        key: "basics",
                        label: "Basics & Ownership",
                        children: (_jsxs(_Fragment, { children: [_jsxs(Row, { gutter: 16, children: [_jsx(Col, { xs: 24, md: 12, children: _jsx(Form.Item, { label: "Name", required: true, children: _jsx(Input, { value: payload.name, onChange: (e) => updatePayload("name", e.target.value) }) }) }), _jsx(Col, { xs: 24, md: 12, children: _jsx(Form.Item, { label: "User (optional)", children: _jsx(Input, { value: payload.user, onChange: (e) => updatePayload("user", e.target.value), placeholder: "Defaults to 'default'" }) }) })] }), _jsxs(Row, { gutter: 16, children: [_jsx(Col, { xs: 24, md: 12, children: _jsx(Form.Item, { label: "Timeout (seconds)", children: _jsx(InputNumber, { min: 0, style: { width: "100%" }, value: payload.timeout, onChange: (value) => updatePayload("timeout", Number(value)) }) }) }), _jsx(Col, { xs: 24, md: 12, children: _jsx(Form.Item, { label: "Retries", children: _jsx(InputNumber, { min: 0, style: { width: "100%" }, value: payload.retries, onChange: (value) => updatePayload("retries", Number(value)) }) }) }), _jsx(Col, { xs: 24, md: 12, children: _jsx(Form.Item, { label: "Queue", children: _jsx(Select, { mode: "tags", value: [payload.queue], onChange: (vals) => updatePayload("queue", vals[vals.length - 1] || "default"), options: (workerHints.queues ?? ["default"]).map((q) => ({ label: q, value: q })), placeholder: "default, ingest, gpu" }) }) })] }), _jsx(Row, { gutter: 16, children: _jsx(Col, { xs: 24, md: 12, children: _jsx(Form.Item, { label: "Priority (higher runs first)", children: _jsx(InputNumber, { min: 0, max: 100, style: { width: "100%" }, value: payload.priority, onChange: (value) => updatePayload("priority", Number(value)) }) }) }) })] })),
                    },
                    {
                        key: "executor",
                        label: "Executor & Code",
                        children: (_jsxs(_Fragment, { children: [_jsxs(Row, { gutter: 16, children: [_jsx(Col, { xs: 24, md: 12, children: executorTypeSelect }), _jsx(Col, { xs: 24, md: 12, children: _jsx(Form.Item, { label: "Arguments", children: _jsx(Input, { value: executor.args?.join(" ") ?? "", onChange: (e) => updateExecutor({ args: e.target.value.split(" ").filter(Boolean) }), placeholder: "--flag value" }) }) })] }), executor.type === "python" && (_jsxs(_Fragment, { children: [_jsxs(Row, { gutter: 16, children: [_jsx(Col, { xs: 24, md: 12, children: _jsx(Form.Item, { label: "Interpreter", children: _jsx(Select, { mode: "tags", value: executor.interpreter ? [executor.interpreter] : [], onChange: (val) => {
                                                                const arr = Array.isArray(val) ? val : [val];
                                                                updateExecutor({ interpreter: arr[arr.length - 1] });
                                                            }, options: (workerHints.pythonVersions ?? []).map((v) => ({ label: v, value: v })), placeholder: "python3, python3.11, uv" }) }) }), _jsx(Col, { xs: 24, md: 12, children: _jsx(Form.Item, { label: "Python Version / Dist (uv friendly)", children: _jsx(Select, { mode: "tags", value: pythonEnv?.python_version ? [pythonEnv.python_version] : [], onChange: (val) => {
                                                                const arr = Array.isArray(val) ? val : [val];
                                                                updatePythonEnv({ python_version: arr[arr.length - 1] });
                                                            }, options: (workerHints.pythonVersions ?? []).map((v) => ({ label: v, value: v })), placeholder: "3.11, 3.12, pypy3" }) }) })] }), _jsx(Form.Item, { label: "Python Code Block", children: _jsx(Input.TextArea, { value: executor.code ?? "", onChange: (e) => updateExecutor({ code: e.target.value }), autoSize: { minRows: 8 }, placeholder: "# Multi-line Python supported" }) }), pythonEnv && (_jsxs(Row, { gutter: 16, children: [_jsx(Col, { xs: 24, md: 8, children: _jsx(Form.Item, { label: "Environment Type", children: _jsx(Select, { value: pythonEnv.type, onChange: (value) => updatePythonEnv({ type: value }), options: [
                                                                { label: "System", value: "system" },
                                                                { label: "Virtualenv", value: "venv" },
                                                                { label: "uv managed", value: "uv" },
                                                            ] }) }) }), _jsx(Col, { xs: 24, md: 8, children: _jsx(Form.Item, { label: "Virtualenv Path (optional)", children: _jsx(Input, { value: pythonEnv.venv_path ?? "", onChange: (e) => updatePythonEnv({ venv_path: e.target.value || null }), placeholder: "/opt/venvs/job" }) }) }), _jsx(Col, { xs: 24, md: 8, children: _jsx(Form.Item, { label: "Requirements File", children: _jsx(Input, { value: pythonEnv.requirements_file ?? "", onChange: (e) => updatePythonEnv({ requirements_file: e.target.value || null }), placeholder: "/workspace/requirements.txt" }) }) }), _jsx(Col, { xs: 24, md: 12, children: _jsx(Form.Item, { label: "Requirements (one per line)", children: _jsx(Input.TextArea, { value: (pythonEnv.requirements ?? []).join("\n"), onChange: (e) => updatePythonEnv({ requirements: parseList(e.target.value) }), autoSize: true }) }) }), _jsx(Col, { xs: 24, md: 12, children: _jsx(Form.Item, { label: "Working Directory", children: _jsx(Input, { value: executor.workdir ?? "", onChange: (e) => updateExecutor({ workdir: e.target.value || null }), placeholder: "/opt/jobs" }) }) }), pythonEnv.type === "uv" && (_jsx(Col, { span: 24, children: _jsx(Alert, { type: "info", showIcon: true, message: "Workers should have uv installed. The requested Python version will be provisioned via uv if available." }) }))] }))] })), (executor.type === "shell" || executor.type === "batch") && (_jsxs(_Fragment, { children: [_jsxs(Row, { gutter: 16, children: [_jsx(Col, { xs: 24, md: 12, children: _jsx(Form.Item, { label: "Shell", children: _jsx(Input, { value: executor.shell ?? (executor.type === "batch" ? "cmd" : "bash"), onChange: (e) => updateExecutor({ shell: e.target.value }) }) }) }), _jsx(Col, { xs: 24, md: 12, children: _jsx(Form.Item, { label: "Working Directory", children: _jsx(Input, { value: executor.workdir ?? "", onChange: (e) => updateExecutor({ workdir: e.target.value || null }), placeholder: "/opt/jobs" }) }) })] }), _jsx(Form.Item, { label: "Script / Code Block", children: _jsx(Input.TextArea, { value: executor.script ?? "", onChange: (e) => updateExecutor({ script: e.target.value }), autoSize: { minRows: 8 }, placeholder: "Multi-line shell or batch scripts supported" }) })] })), executor.type === "external" && (_jsxs(_Fragment, { children: [_jsx(Form.Item, { label: "Command / Binary Path", children: _jsx(Input, { value: executor.command ?? "", onChange: (e) => updateExecutor({ command: e.target.value }) }) }), _jsx(Form.Item, { label: "Working Directory", children: _jsx(Input, { value: executor.workdir ?? "", onChange: (e) => updateExecutor({ workdir: e.target.value || null }), placeholder: "/opt/jobs" }) })] })), _jsx(Form.Item, { label: "Environment Variables (KEY=VALUE per line)", children: _jsx(Input.TextArea, { value: executor.env
                                            ? Object.entries(executor.env)
                                                .map(([k, v]) => `${k}=${v}`)
                                                .join("\n")
                                            : "", onChange: (e) => {
                                            const envLines = e.target.value.split("\n");
                                            const env = {};
                                            envLines.forEach((line) => {
                                                const [k, ...rest] = line.split("=");
                                                if (k && rest.length) {
                                                    env[k.trim()] = rest.join("=").trim();
                                                }
                                            });
                                            updateExecutor({ env });
                                        }, autoSize: true }) })] })),
                    },
                    {
                        key: "schedule",
                        label: "Schedule & Windows",
                        children: (_jsxs(_Fragment, { children: [_jsxs(Row, { gutter: 16, align: "middle", children: [_jsx(Col, { xs: 24, md: 8, children: _jsx(Form.Item, { label: "Mode", children: _jsx(Select, { value: schedule.mode, onChange: (mode) => updateSchedule({ mode, next_run_at: null }), options: [
                                                        { label: "Immediate", value: "immediate" },
                                                        { label: "Interval", value: "interval" },
                                                        { label: "Cron", value: "cron" },
                                                    ] }) }) }), _jsx(Col, { xs: 24, md: 8, children: _jsx(Form.Item, { label: "Enabled", children: _jsx(Switch, { checked: schedule.enabled, onChange: (checked) => updateSchedule({ enabled: checked }) }) }) }), _jsx(Col, { xs: 24, md: 8, children: _jsxs(Typography.Text, { type: "secondary", children: ["Next run:", " ", !schedule.enabled
                                                        ? "Disabled"
                                                        : schedule.next_run_at
                                                            ? new Date(schedule.next_run_at).toLocaleString()
                                                            : schedule.mode === "immediate"
                                                                ? "Immediately"
                                                                : "Pending"] }) })] }), schedule.mode === "interval" && (_jsx(Row, { gutter: 16, children: _jsx(Col, { xs: 24, md: 12, children: _jsx(Form.Item, { label: "Interval (seconds)", children: _jsx(InputNumber, { min: 1, style: { width: "100%" }, value: schedule.interval_seconds ?? 300, onChange: (value) => updateSchedule({ interval_seconds: Number(value) }) }) }) }) })), schedule.mode === "cron" && (_jsx(Row, { gutter: 16, children: _jsx(Col, { span: 24, children: _jsx(Form.Item, { label: "Cron Expression", children: _jsx(Input, { value: schedule.cron ?? "", onChange: (e) => updateSchedule({ cron: e.target.value }), placeholder: "*/5 * * * *" }) }) }) })), (schedule.mode === "interval" || schedule.mode === "cron") && (_jsxs(Row, { gutter: 16, children: [_jsx(Col, { xs: 24, md: 12, children: _jsx(Form.Item, { label: "Start At", children: _jsx(Input, { type: "datetime-local", value: toInputValue(schedule.start_at), onChange: (e) => updateSchedule({ start_at: fromInputValue(e.target.value) }) }) }) }), _jsx(Col, { xs: 24, md: 12, children: _jsx(Form.Item, { label: "End At", children: _jsx(Input, { type: "datetime-local", value: toInputValue(schedule.end_at), onChange: (e) => updateSchedule({ end_at: fromInputValue(e.target.value) }) }) }) })] }))] })),
                    },
                    {
                        key: "completion",
                        label: "Completion Criteria",
                        children: (_jsxs(_Fragment, { children: [_jsx(Row, { gutter: 16, children: _jsx(Col, { span: 24, children: _jsx(Form.Item, { label: "Exit Codes", children: _jsx(Input, { value: completion.exit_codes.join(", "), onChange: (e) => {
                                                    const values = parseList(e.target.value)
                                                        .map((c) => Number(c))
                                                        .filter((n) => !Number.isNaN(n));
                                                    updateCompletion({ exit_codes: values.length ? values : [] });
                                                }, placeholder: "0, 2" }) }) }) }), _jsxs(Row, { gutter: 16, children: [_jsx(Col, { xs: 24, md: 12, children: _jsx(Form.Item, { label: "Stdout must contain", children: _jsx(Input.TextArea, { value: completion.stdout_contains.join("\n"), onChange: (e) => setCompletionList("stdout_contains", e.target.value), placeholder: "ready", autoSize: true }) }) }), _jsx(Col, { xs: 24, md: 12, children: _jsx(Form.Item, { label: "Stdout must NOT contain", children: _jsx(Input.TextArea, { value: completion.stdout_not_contains.join("\n"), onChange: (e) => setCompletionList("stdout_not_contains", e.target.value), placeholder: "error", autoSize: true }) }) })] }), _jsxs(Row, { gutter: 16, children: [_jsx(Col, { xs: 24, md: 12, children: _jsx(Form.Item, { label: "Stderr must contain", children: _jsx(Input.TextArea, { value: completion.stderr_contains.join("\n"), onChange: (e) => setCompletionList("stderr_contains", e.target.value), autoSize: true }) }) }), _jsx(Col, { xs: 24, md: 12, children: _jsx(Form.Item, { label: "Stderr must NOT contain", children: _jsx(Input.TextArea, { value: completion.stderr_not_contains.join("\n"), onChange: (e) => setCompletionList("stderr_not_contains", e.target.value), autoSize: true }) }) })] })] })),
                    },
                    {
                        key: "affinity",
                        label: "Affinity & Placement",
                        children: (_jsxs(_Fragment, { children: [_jsx(Alert, { type: "info", showIcon: true, message: "Use the worker-derived dropdowns to target specific pools. You can also type new values to create ad-hoc affinities.", style: { marginBottom: 12 } }), _jsxs(Row, { gutter: 16, children: [_jsx(Col, { xs: 24, md: 8, children: _jsx(Form.Item, { label: "Target OS", children: _jsx(Select, { mode: "tags", value: payload.affinity.os, onChange: (vals) => updateAffinity("os", vals), options: workerHints.os.map((v) => ({ label: v, value: v })), placeholder: "linux, windows" }) }) }), _jsx(Col, { xs: 24, md: 8, children: _jsx(Form.Item, { label: "Tags", children: _jsx(Select, { mode: "tags", value: payload.affinity.tags, onChange: (vals) => updateAffinity("tags", vals), options: workerHints.tags.map((v) => ({ label: v, value: v })), placeholder: "gpu, python, ingest" }) }) }), _jsx(Col, { xs: 24, md: 8, children: _jsx(Form.Item, { label: "Allowed Users", children: _jsx(Select, { mode: "tags", value: payload.affinity.allowed_users, onChange: (vals) => updateAffinity("allowed_users", vals), options: workerHints.users.map((v) => ({ label: v, value: v })), placeholder: "alice, bob" }) }) })] }), _jsxs(Row, { gutter: 16, children: [_jsx(Col, { xs: 24, md: 8, children: _jsx(Form.Item, { label: "Hostnames", children: _jsx(Select, { mode: "tags", value: payload.affinity.hostnames ?? [], onChange: (vals) => updateAffinity("hostnames", vals), options: workerHints.hostnames.map((v) => ({ label: v, value: v })), placeholder: "worker-1, batch-2" }) }) }), _jsx(Col, { xs: 24, md: 8, children: _jsx(Form.Item, { label: "Subnets / CIDRs", children: _jsx(Select, { mode: "tags", value: payload.affinity.subnets ?? [], onChange: (vals) => updateAffinity("subnets", vals), options: workerHints.subnets.map((v) => ({ label: v, value: v })), placeholder: "10.0.0.0/24" }) }) }), _jsx(Col, { xs: 24, md: 8, children: _jsx(Form.Item, { label: "Deployment Types", children: _jsx(Select, { mode: "tags", value: payload.affinity.deployment_types ?? [], onChange: (vals) => updateAffinity("deployment_types", vals), options: workerHints.deployments.map((v) => ({ label: v, value: v })), placeholder: "docker, kubernetes, bare-metal" }) }) })] })] })),
                    },
                ] }), _jsx(Divider, {}), _jsxs(Space, { wrap: true, children: [_jsx(Button, { type: "primary", htmlType: "submit", loading: submitting, children: selectedJob ? "Update Job" : "Submit Job" }), _jsx(Button, { onClick: handleValidate, loading: validating, children: "Validate" }), !selectedJob && (_jsx(Button, { onClick: () => {
                            const normalized = { ...payload, user: payload.user?.trim() || "default" };
                            onAdhocRun(normalized);
                        }, disabled: submitting, type: "dashed", children: "Run Adhoc" })), selectedJob && (_jsx(Button, { onClick: onManualRun, type: "default", children: "Run Now" })), selectedJob && (_jsx(Button, { onClick: onReset, danger: true, children: "New Job" }))] }), statusMessage && _jsx(Typography.Paragraph, { style: { marginTop: "0.5rem" }, children: statusMessage })] }));
}
