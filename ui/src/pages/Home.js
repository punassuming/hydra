import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Row, Col, Card, Typography, Space, Button, Modal, Divider, Alert } from "antd";
import { JobForm } from "../components/JobForm";
import { JobList } from "../components/JobList";
import { JobRuns } from "../components/JobRuns";
import { EventsFeed } from "../components/EventsFeed";
import { JobOverview } from "../components/JobOverview";
import { useSchedulerEvents } from "../hooks/useEvents";
import { createJob, fetchJobs, runAdhocJob, runJobNow, updateJob, validateJob } from "../api/jobs";
import { WorkersMini } from "../components/WorkersMini";
export function HomePage() {
    const queryClient = useQueryClient();
    const [selectedJobId, setSelectedJobId] = useState(null);
    const [statusMessage, setStatusMessage] = useState();
    const [validating, setValidating] = useState(false);
    const [modalVisible, setModalVisible] = useState(false);
    const events = useSchedulerEvents();
    const jobsQuery = useQuery({
        queryKey: ["jobs"],
        queryFn: fetchJobs,
        refetchInterval: 5000,
    });
    const jobs = jobsQuery.data ?? [];
    const selectedJob = jobs.find((j) => j._id === selectedJobId);
    const createMutation = useMutation({
        mutationFn: createJob,
        onSuccess: (data) => {
            queryClient.invalidateQueries({ queryKey: ["jobs"] });
            setSelectedJobId(data._id);
            setStatusMessage("Job created and queued");
            setModalVisible(false);
        },
        onError: (err) => setStatusMessage(err.message),
    });
    const updateMutation = useMutation({
        mutationFn: (payload) => updateJob(selectedJobId, payload),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["jobs"] });
            setStatusMessage("Job updated");
            setModalVisible(false);
        },
        onError: (err) => setStatusMessage(err.message),
    });
    const manualRunMutation = useMutation({
        mutationFn: (jobId) => runJobNow(jobId),
        onSuccess: () => setStatusMessage("Manual run queued"),
        onError: (err) => setStatusMessage(err.message),
    });
    const adhocMutation = useMutation({
        mutationFn: runAdhocJob,
        onSuccess: (data) => {
            queryClient.invalidateQueries({ queryKey: ["jobs"] });
            setSelectedJobId(data._id);
            setStatusMessage("Adhoc job queued");
            setModalVisible(false);
        },
        onError: (err) => setStatusMessage(err.message),
    });
    const handleSubmit = (payload) => {
        setStatusMessage(undefined);
        if (selectedJobId) {
            updateMutation.mutate(payload);
        }
        else {
            createMutation.mutate(payload);
        }
    };
    const handleValidate = async (payload) => {
        setValidating(true);
        setStatusMessage("Validating…");
        try {
            const result = await validateJob(payload);
            if (result.valid) {
                const next = result.next_run_at ? ` – next run ${new Date(result.next_run_at).toLocaleString()}` : "";
                setStatusMessage(`Validation passed${next}`);
            }
            else {
                setStatusMessage(result.errors.join(", "));
            }
        }
        catch (err) {
            setStatusMessage(err.message);
        }
        finally {
            setValidating(false);
        }
    };
    const handleManualRun = () => {
        if (selectedJobId) {
            manualRunMutation.mutate(selectedJobId);
        }
    };
    const handleAdhocRun = (payload) => {
        setStatusMessage(undefined);
        adhocMutation.mutate(payload);
    };
    const resetSelection = () => {
        setSelectedJobId(null);
        setStatusMessage(undefined);
    };
    return (_jsxs(Space, { direction: "vertical", size: "large", style: { width: "100%" }, children: [_jsxs(Card, { children: [_jsxs(Row, { justify: "space-between", align: "middle", children: [_jsxs(Col, { children: [_jsx(Typography.Title, { level: 3, style: { marginBottom: 0 }, children: "Hydra Jobs Control Plane" }), _jsx(Typography.Text, { type: "secondary", children: "Submit, schedule, and inspect jobs across heterogeneous workers with queue/affinity aware placement." })] }), _jsx(Col, { children: _jsxs(Space, { children: [_jsx(Button, { type: "primary", onClick: () => setModalVisible(true), children: "New Job" }), _jsx(Button, { disabled: !selectedJob, onClick: () => setModalVisible(true), children: "Edit Selected" }), selectedJob && (_jsx(Button, { onClick: handleManualRun, children: "Run Selected" }))] }) })] }), statusMessage && (_jsx(Typography.Paragraph, { style: { marginTop: 16 }, children: statusMessage }))] }), _jsx(Alert, { type: "info", showIcon: true, message: "Hydra stitches together queues, priorities, affinities, and multiple executors (python, shell, batch, external). Use the nav to jump to Status (health/queues), History (runs), Browse (jobs/runs), and Workers (capabilities)." }), _jsxs(Card, { children: [_jsx(Typography.Title, { level: 4, children: "How to use" }), _jsx(Typography.Paragraph, { children: "1) Create or edit a job with executor, queue/priority, schedule, and affinity. 2) Validate or run now (adhoc/manual). 3) Track live runs from Status and logs modal (supports live streaming). 4) Inspect history or browse cross-job runs. 5) Tune placement via queues/affinity and worker capabilities under Workers." })] }), _jsx(Card, { id: "job-list", title: "Jobs", children: _jsx(JobList, { jobs: jobs, loading: jobsQuery.isLoading, selectedId: selectedJobId, onSelect: (job) => setSelectedJobId(job._id), onEdit: () => setModalVisible(true) }) }), _jsx(JobOverview, {}), _jsx(WorkersMini, {}), _jsxs(Row, { gutter: [16, 16], children: [_jsx(Col, { xs: 24, lg: 12, children: _jsx(Card, { id: "job-history", title: "Job History", children: _jsx(JobRuns, { jobId: selectedJobId }) }) }), _jsx(Col, { xs: 24, lg: 12, children: _jsx(Card, { id: "events", title: "Events", children: _jsx(EventsFeed, { events: events }) }) })] }), _jsxs(Modal, { title: selectedJob ? `Edit Job – ${selectedJob.name}` : "Create Job", open: modalVisible, onCancel: () => {
                    setModalVisible(false);
                    resetSelection();
                }, footer: null, width: 1100, destroyOnClose: true, bodyStyle: { background: "#0f172a0d", borderRadius: 12 }, children: [_jsx(JobForm, { selectedJob: selectedJob, onSubmit: handleSubmit, onValidate: handleValidate, onManualRun: handleManualRun, onAdhocRun: handleAdhocRun, submitting: createMutation.isPending || updateMutation.isPending, validating: validating, statusMessage: statusMessage, onReset: resetSelection }), _jsx(Divider, {}), _jsx(Typography.Text, { type: "secondary", children: "Jobs are persisted immediately. Closing this dialog will not discard saved changes." })] })] }));
}
