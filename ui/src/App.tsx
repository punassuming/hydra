import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Layout, Row, Col, Card, Typography, Space } from "antd";
import { JobForm } from "./components/JobForm";
import { JobList } from "./components/JobList";
import { JobRuns } from "./components/JobRuns";
import { WorkersPanel } from "./components/WorkersPanel";
import { EventsFeed } from "./components/EventsFeed";
import { JobOverview } from "./components/JobOverview";
import { createJob, fetchJobs, JobPayload, runJobNow, runAdhocJob, updateJob, validateJob } from "./api/jobs";
import { useSchedulerEvents } from "./hooks/useEvents";

function App() {
  const { Header, Content } = Layout;
  const queryClient = useQueryClient();
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState<string>();
  const [validating, setValidating] = useState(false);
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
    },
    onError: (err: Error) => setStatusMessage(err.message),
  });

  const updateMutation = useMutation({
    mutationFn: (payload: JobPayload) => updateJob(selectedJobId!, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      setStatusMessage("Job updated");
    },
    onError: (err: Error) => setStatusMessage(err.message),
  });

  const manualRunMutation = useMutation({
    mutationFn: (jobId: string) => runJobNow(jobId),
    onSuccess: () => {
      setStatusMessage("Manual run queued");
    },
    onError: (err: Error) => setStatusMessage(err.message),
  });

  const adhocMutation = useMutation({
    mutationFn: runAdhocJob,
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      setSelectedJobId(data._id);
      setStatusMessage("Adhoc job queued");
    },
    onError: (err: Error) => setStatusMessage(err.message),
  });

  const handleSubmit = (payload: JobPayload) => {
    setStatusMessage(undefined);
    if (selectedJobId) {
      updateMutation.mutate(payload);
    } else {
      createMutation.mutate(payload);
    }
  };

  const handleValidate = async (payload: JobPayload) => {
    setValidating(true);
    setStatusMessage("Validating…");
    try {
      const result = await validateJob(payload);
      if (result.valid) {
        const next = result.next_run_at ? ` – next run ${new Date(result.next_run_at).toLocaleString()}` : "";
        setStatusMessage(`Validation passed${next}`);
      } else {
        setStatusMessage(result.errors.join(", "));
      }
    } catch (err) {
      setStatusMessage((err as Error).message);
    } finally {
      setValidating(false);
    }
  };

  const handleManualRun = () => {
    if (selectedJobId) {
      manualRunMutation.mutate(selectedJobId);
    }
  };

  const handleAdhocRun = (payload: JobPayload) => {
    setStatusMessage(undefined);
    adhocMutation.mutate(payload);
  };

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Header style={{ background: "#0f172a", padding: "0 24px" }}>
        <Space direction="vertical" size={0}>
          <Typography.Title level={3} style={{ color: "#fff", margin: 0 }}>
            Hydra Scheduler
          </Typography.Title>
          <Typography.Text style={{ color: "#cbd5f5" }}>Submit, monitor, and rerun jobs across your worker pool</Typography.Text>
        </Space>
      </Header>
      <Content style={{ padding: 24, background: "#f5f7fb" }}>
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={16}>
            <Card title="Job Builder" bordered={false}>
              <JobForm
                selectedJob={selectedJob}
                onSubmit={handleSubmit}
                onValidate={handleValidate}
                onManualRun={handleManualRun}
                onAdhocRun={handleAdhocRun}
                submitting={createMutation.isPending || updateMutation.isPending}
                validating={validating}
                statusMessage={statusMessage}
                onReset={() => {
                  setSelectedJobId(null);
                  setStatusMessage(undefined);
                }}
              />
            </Card>
          </Col>
          <Col xs={24} lg={8}>
            <WorkersPanel />
          </Col>
        </Row>
        <Row gutter={[16, 16]} style={{ marginTop: 8 }}>
          <Col xs={24} lg={12}>
            <JobList jobs={jobs} loading={jobsQuery.isLoading} selectedId={selectedJobId} onSelect={(job) => setSelectedJobId(job._id)} />
          </Col>
          <Col xs={24} lg={12}>
            <JobRuns jobId={selectedJobId} />
          </Col>
        </Row>
        <Row gutter={[16, 16]} style={{ marginTop: 8 }}>
          <Col xs={24} lg={12}>
            <JobOverview />
          </Col>
          <Col xs={24} lg={12}>
            <EventsFeed events={events} />
          </Col>
        </Row>
      </Content>
    </Layout>
  );
}

export default App;
