import { useEffect, useMemo, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Card, Space, Typography, Tabs, Button, Tag, Descriptions, message, Modal, Input, Form, Popconfirm } from "antd";
import { DownloadOutlined } from "@ant-design/icons";
import { JobForm } from "../components/JobForm";
import { JobRuns } from "../components/JobRuns";
import { JobGridView } from "../components/JobGridView";
import { JobGanttView } from "../components/JobGanttView";
import { JobGraphView } from "../components/JobGraphView";
import { JobPayload, ValidationResult, deleteJob, fetchJob, fetchJobRuns, runJobNow, killRun, backfillJob, toExportPayload, updateJob, validateJob } from "../api/jobs";
import { useActiveDomain } from "../context/ActiveDomainContext";
import { downloadJson, slugify } from "../utils/download";

export function JobDetailPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [messageApi, contextHolder] = message.useMessage();
  const [activeTab, setActiveTab] = useState(() => localStorage.getItem("hydra_job_detail_tab") || "overview");
  const { domain } = useActiveDomain();
  const [paramsModalVisible, setParamsModalVisible] = useState(false);
  const [paramsText, setParamsText] = useState("");
  const [backfillModalVisible, setBackfillModalVisible] = useState(false);
  const [backfillStartDate, setBackfillStartDate] = useState("");
  const [backfillEndDate, setBackfillEndDate] = useState("");
  const [editModalVisible, setEditModalVisible] = useState(false);
  const [editStatusMessage, setEditStatusMessage] = useState<string>();
  const [validating, setValidating] = useState(false);

  const jobQuery = useQuery({
    queryKey: ["job", domain, jobId],
    queryFn: () => fetchJob(jobId!),
    enabled: Boolean(jobId),
  });

  const runsQuery = useQuery({
    queryKey: ["job-runs", domain, jobId],
    queryFn: () => fetchJobRuns(jobId!),
    enabled: Boolean(jobId),
    refetchInterval: 5000,
  });
  const job = jobQuery.data;

  const parseParams = (text: string): Record<string, string> => {
    const result: Record<string, string> = {};
    text.split("\n").filter((line) => line.trim()).forEach((line) => {
      const [k, ...rest] = line.split("=");
      if (k?.trim() && rest.length) result[k.trim()] = rest.join("=").trim();
    });
    return result;
  };

  const manualRun = useMutation({
    mutationFn: ({ id, params }: { id: string; params?: Record<string, string> }) => runJobNow(id, params),
    onSuccess: () => {
      messageApi.success("Run queued");
      queryClient.invalidateQueries({ queryKey: ["job-runs", domain, jobId] });
      queryClient.invalidateQueries({ queryKey: ["job-grid", domain, jobId] });
      queryClient.invalidateQueries({ queryKey: ["job-gantt", domain, jobId] });
      queryClient.invalidateQueries({ queryKey: ["job-graph", domain, jobId] });
    },
  });

  const updateMutation = useMutation({
    mutationFn: (payload: JobPayload) => updateJob(jobId!, payload),
    onSuccess: () => {
      messageApi.success("Job updated");
      queryClient.invalidateQueries({ queryKey: ["jobs", domain] });
      queryClient.invalidateQueries({ queryKey: ["job", domain, jobId] });
      setEditModalVisible(false);
      setEditStatusMessage(undefined);
    },
    onError: (err: Error) => {
      setEditStatusMessage(err.message);
      messageApi.error(err.message);
    },
  });

  const toJobPayload = (source: any): JobPayload => ({
    name: source.name,
    user: source.user || "default",
    priority: source.priority ?? 5,
    affinity: source.affinity,
    executor: source.executor,
    retries: source.retries ?? 0,
    timeout: source.timeout ?? 30,
    bypass_concurrency: source.bypass_concurrency ?? false,
    source: source.source ?? null,
    schedule: source.schedule,
    completion: source.completion,
    tags: source.tags ?? [],
    depends_on: source.depends_on ?? [],
    max_retries: source.max_retries ?? 0,
    retry_delay_seconds: source.retry_delay_seconds ?? 0,
    on_failure_webhooks: source.on_failure_webhooks ?? [],
    on_failure_email_to: source.on_failure_email_to ?? [],
    on_failure_email_credential_ref: source.on_failure_email_credential_ref ?? "",
    sla_max_duration_seconds: source.sla_max_duration_seconds ?? null,
  });

  const toggleActiveMutation = useMutation({
    mutationFn: (enabled: boolean) => updateJob(jobId!, { ...toJobPayload(job), schedule: { ...job!.schedule, enabled } }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["jobs", domain] });
      queryClient.invalidateQueries({ queryKey: ["job", domain, jobId] });
      messageApi.success("Job schedule state updated");
    },
    onError: (err: Error) => messageApi.error(err.message),
  });

  const handleValidate = async (payload: JobPayload): Promise<ValidationResult | undefined> => {
    setValidating(true);
    setEditStatusMessage("Validating…");
    try {
      const result = await validateJob(payload);
      if (result.valid) {
        const next = result.next_run_at ? ` – next run ${new Date(result.next_run_at).toLocaleString()}` : "";
        setEditStatusMessage(`Validation passed${next}`);
      } else {
        setEditStatusMessage(result.errors.join(", "));
      }
      return result;
    } catch (err) {
      setEditStatusMessage((err as Error).message);
      return undefined;
    } finally {
      setValidating(false);
    }
  };

  const killMutation = useMutation({
    mutationFn: (runId: string) => killRun(runId),
    onSuccess: () => {
      messageApi.success("Kill signal sent");
      queryClient.invalidateQueries({ queryKey: ["job-runs", domain, jobId] });
    },
    onError: () => messageApi.error("Failed to send kill signal"),
  });

  const backfillMutation = useMutation({
    mutationFn: ({ id, start, end }: { id: string; start: string; end: string }) =>
      backfillJob(id, start, end),
    onSuccess: (data) => {
      messageApi.success(`Backfill queued: ${data.queued_count} runs (${data.start_date} → ${data.end_date})`);
      queryClient.invalidateQueries({ queryKey: ["job-runs", domain, jobId] });
    },
    onError: () => messageApi.error("Failed to queue backfill"),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteJob(id),
    onSuccess: () => {
      message.success("Job deleted");
      queryClient.invalidateQueries({ queryKey: ["jobs", domain] });
      navigate("/");
    },
    onError: (err: Error) => messageApi.error(err.message),
  });

  const handleRunNow = () => {
    setParamsModalVisible(true);
  };

  const handleRunWithParams = () => {
    const params = parseParams(paramsText);
    manualRun.mutate({ id: job!._id, params: Object.keys(params).length ? params : undefined });
    setParamsModalVisible(false);
    setParamsText("");
  };

  const handleBackfill = () => {
    const today = new Date().toISOString().slice(0, 10);
    setBackfillStartDate(today);
    setBackfillEndDate(today);
    setBackfillModalVisible(true);
  };

  const handleBackfillSubmit = () => {
    if (!backfillStartDate || !backfillEndDate) {
      messageApi.error("Please select both start and end dates");
      return;
    }
    backfillMutation.mutate({ id: job!._id, start: backfillStartDate, end: backfillEndDate });
    setBackfillModalVisible(false);
  };

  useEffect(() => {
    localStorage.setItem("hydra_job_detail_tab", activeTab);
  }, [activeTab]);

  const runningRuns = (runsQuery.data ?? []).filter((r) => r.status === "running");

  const tabItems = useMemo(() => {
    if (!job) return [];
    return [
      {
        key: "overview",
        label: "Overview",
        children: (
          <Descriptions bordered column={1} size="small">
            <Descriptions.Item label="Job ID">{job._id}</Descriptions.Item>
            <Descriptions.Item label="Name">{job.name}</Descriptions.Item>
            <Descriptions.Item label="User">{job.user}</Descriptions.Item>
            <Descriptions.Item label="Executor">{job.executor.type}</Descriptions.Item>
            <Descriptions.Item label="Bypass Concurrency">
              {job.bypass_concurrency ? "enabled" : "disabled"}
            </Descriptions.Item>
            <Descriptions.Item label="Schedule Mode">{job.schedule.mode === "immediate" ? "manual" : job.schedule.mode}</Descriptions.Item>
            <Descriptions.Item label="Retries">{job.retries}</Descriptions.Item>
            <Descriptions.Item label="Timeout">{job.timeout}s</Descriptions.Item>
            {(job.max_retries ?? 0) > 0 && (
              <Descriptions.Item label="Max Scheduler Retries">{job.max_retries} (delay: {job.retry_delay_seconds ?? 0}s)</Descriptions.Item>
            )}
            {(job.depends_on ?? []).length > 0 && (
              <Descriptions.Item label="Depends On">{(job.depends_on ?? []).join(", ")}</Descriptions.Item>
            )}
            {(job.on_failure_webhooks ?? []).length > 0 && (
              <Descriptions.Item label="Failure Webhooks">{(job.on_failure_webhooks ?? []).join(", ")}</Descriptions.Item>
            )}
            {(job.on_failure_email_to ?? []).length > 0 && (
              <Descriptions.Item label="Failure Emails">{(job.on_failure_email_to ?? []).join(", ")}</Descriptions.Item>
            )}
            {job.on_failure_email_credential_ref && (
              <Descriptions.Item label="Email Credential Ref">{job.on_failure_email_credential_ref}</Descriptions.Item>
            )}
          </Descriptions>
        ),
      },
      {
        key: "grid",
        label: "Grid",
        children: jobId ? <JobGridView jobId={jobId} /> : null,
      },
      {
        key: "runs",
        label: "Runs",
        children: (
          <Space direction="vertical" style={{ width: "100%" }}>
            {runningRuns.length > 0 && (
              <Space wrap>
                {runningRuns.map((run) => (
                  <Button
                    key={run._id}
                    danger
                    size="small"
                    onClick={() => killMutation.mutate(run._id)}
                    loading={killMutation.isPending}
                  >
                    Stop run {run._id.slice(0, 8)}
                  </Button>
                ))}
              </Space>
            )}
            <JobRuns jobId={jobId} runs={runsQuery.data ?? []} loading={runsQuery.isLoading} onKillRun={(runId) => killMutation.mutate(runId)} />
          </Space>
        ),
      },
      {
        key: "gantt",
        label: "Gantt",
        children: jobId ? <JobGanttView jobId={jobId} /> : null,
      },
      {
        key: "graph",
        label: "Graph",
        children: jobId ? <JobGraphView jobId={jobId} /> : null,
      },
      {
        key: "code",
        label: "Code",
        children: (
          <Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>
            {job.executor.type === "python" ? job.executor.code : job.executor.type === "shell" ? job.executor.script : "No inline code"}
          </Typography.Paragraph>
        ),
      },
    ];
  }, [job, jobId, runsQuery.data, runsQuery.isLoading, runningRuns, killMutation]);

  if (!jobId) {
    return <Typography.Text>Select a job from the jobs list.</Typography.Text>;
  }

  if (jobQuery.isLoading) {
    return <Typography.Text>Loading job…</Typography.Text>;
  }

  if (!job) {
    return <Typography.Text>Job not found.</Typography.Text>;
  }

  return (
    <Space direction="vertical" style={{ width: "100%" }} size="large">
      {contextHolder}
      <Card>
        <Space direction="vertical" style={{ width: "100%" }}>
          <Space align="center" wrap>
            <Typography.Title level={3} style={{ marginBottom: 0 }}>
              {job.name}
            </Typography.Title>
            <Tag color="blue">{job.executor.type}</Tag>
            <Tag color={job.schedule.enabled ? "green" : "default"}>{job.schedule.mode === "immediate" ? "manual" : job.schedule.mode}</Tag>
          </Space>
          <Space>
            <Button
              onClick={() => {
                setEditStatusMessage(undefined);
                setEditModalVisible(true);
              }}
            >
              Edit Job
            </Button>
            <Button
              onClick={() => toggleActiveMutation.mutate(!job.schedule.enabled)}
              loading={toggleActiveMutation.isPending}
            >
              {job.schedule.enabled ? "Deactivate" : "Activate"}
            </Button>
            <Button onClick={handleRunNow} loading={manualRun.isPending}>Run Now</Button>
            <Button onClick={handleBackfill} loading={backfillMutation.isPending}>Backfill</Button>
            <Button
              icon={<DownloadOutlined />}
              onClick={() => downloadJson(`${slugify(job.name)}.json`, toExportPayload(job))}
            >
              Export JSON
            </Button>
            <Popconfirm
              title={`Delete job "${job.name}"?`}
              description="The definition and pending queue entries are removed. Run history is preserved."
              okText="Delete"
              okButtonProps={{ danger: true }}
              onConfirm={() => deleteMutation.mutate(job._id)}
            >
              <Button danger loading={deleteMutation.isPending}>Delete</Button>
            </Popconfirm>
            <Button onClick={() => navigate("/")}>Back to Jobs</Button>
          </Space>
        </Space>
      </Card>
      <Tabs items={tabItems} activeKey={activeTab} onChange={setActiveTab} />
      <Modal
        title={`Edit Job – ${job.name}`}
        open={editModalVisible}
        onCancel={() => {
          setEditModalVisible(false);
          setEditStatusMessage(undefined);
        }}
        footer={null}
        width={980}
        destroyOnClose
      >
        <JobForm
          selectedJob={job}
          onSubmit={(payload) => {
            setEditStatusMessage("Saving job…");
            updateMutation.mutate(payload);
          }}
          onValidate={handleValidate}
          onManualRun={handleRunNow}
          onAdhocRun={() => messageApi.info("Adhoc runs are available from the New Job flow on Home.")}
          submitting={updateMutation.isPending}
          validating={validating}
          statusMessage={editStatusMessage}
          onReset={() => {}}
          onCancel={() => {
            setEditModalVisible(false);
            setEditStatusMessage(undefined);
          }}
        />
      </Modal>
      <Modal
        open={paramsModalVisible}
        title="Run with Parameters"
        onOk={handleRunWithParams}
        onCancel={() => { setParamsModalVisible(false); setParamsText(""); }}
        okText="Run"
      >
        <Form layout="vertical">
          <Form.Item
            label="Runtime Parameters (KEY=VALUE, one per line)"
            extra="These will be injected as environment variables into the job process."
          >
            <Input.TextArea
              value={paramsText}
              onChange={(e) => setParamsText(e.target.value)}
              placeholder={"MY_PARAM=hello\nANOTHER=world"}
              autoSize={{ minRows: 4 }}
            />
          </Form.Item>
        </Form>
      </Modal>
      <Modal
        open={backfillModalVisible}
        title="Backfill: Queue Historical Runs"
        onOk={handleBackfillSubmit}
        onCancel={() => setBackfillModalVisible(false)}
        okText="Queue Backfill"
        confirmLoading={backfillMutation.isPending}
      >
        <Form layout="vertical">
          <Form.Item
            label="Start Date"
            extra="First day of the backfill range (inclusive)."
          >
            <Input
              type="date"
              value={backfillStartDate}
              onChange={(e) => setBackfillStartDate(e.target.value)}
            />
          </Form.Item>
          <Form.Item
            label="End Date"
            extra="Last day of the backfill range (inclusive). Maximum 366 days."
          >
            <Input
              type="date"
              value={backfillEndDate}
              onChange={(e) => setBackfillEndDate(e.target.value)}
            />
          </Form.Item>
          <Typography.Text type="secondary">
            One run will be queued per day with <code>HYDRA_EXECUTION_DATE</code> set to each date (YYYY-MM-DD).
          </Typography.Text>
        </Form>
      </Modal>
    </Space>
  );
}
