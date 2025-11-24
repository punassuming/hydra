import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Row, Col, Card, Typography, Space, Button, Modal, Divider, Alert } from "antd";
import { JobForm } from "../components/JobForm";
import { JobList } from "../components/JobList";
import { JobRuns } from "../components/JobRuns";
import { EventsFeed } from "../components/EventsFeed";
import { JobOverview } from "../components/JobOverview";
import { useSchedulerEvents } from "../hooks/useEvents";
import { createJob, fetchJobs, JobPayload, runAdhocJob, runJobNow, updateJob, validateJob } from "../api/jobs";
import { WorkersMini } from "../components/WorkersMini";

export function HomePage() {
  const queryClient = useQueryClient();
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState<string>();
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
    onError: (err: Error) => setStatusMessage(err.message),
  });

  const updateMutation = useMutation({
    mutationFn: (payload: JobPayload) => updateJob(selectedJobId!, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      setStatusMessage("Job updated");
      setModalVisible(false);
    },
    onError: (err: Error) => setStatusMessage(err.message),
  });

  const manualRunMutation = useMutation({
    mutationFn: (jobId: string) => runJobNow(jobId),
    onSuccess: () => setStatusMessage("Manual run queued"),
    onError: (err: Error) => setStatusMessage(err.message),
  });

  const adhocMutation = useMutation({
    mutationFn: runAdhocJob,
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      setSelectedJobId(data._id);
      setStatusMessage("Adhoc job queued");
      setModalVisible(false);
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

  const resetSelection = () => {
    setSelectedJobId(null);
    setStatusMessage(undefined);
  };

  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <Card>
        <Row justify="space-between" align="middle">
          <Col>
            <Typography.Title level={3} style={{ marginBottom: 0 }}>
              Hydra Jobs Control Plane
            </Typography.Title>
            <Typography.Text type="secondary">
              Submit, schedule, and inspect jobs across heterogeneous workers with queue/affinity aware placement.
            </Typography.Text>
          </Col>
          <Col>
            <Space>
              <Button type="primary" onClick={() => setModalVisible(true)}>
                New Job
              </Button>
              <Button disabled={!selectedJob} onClick={() => setModalVisible(true)}>
                Edit Selected
              </Button>
              {selectedJob && (
                <Button onClick={handleManualRun}>Run Selected</Button>
              )}
            </Space>
          </Col>
        </Row>
        {statusMessage && (
          <Typography.Paragraph style={{ marginTop: 16 }}>{statusMessage}</Typography.Paragraph>
        )}
      </Card>

      <Alert
        type="info"
        showIcon
        message="Hydra stitches together queues, priorities, affinities, and multiple executors (python, shell, batch, external). Use the nav to jump to Status (health/queues), History (runs), Browse (jobs/runs), and Workers (capabilities)."
      />

      <Card>
        <Typography.Title level={4}>How to use</Typography.Title>
        <Typography.Paragraph>
          1) Create or edit a job with executor, queue/priority, schedule, and affinity. 2) Validate or run now (adhoc/manual).
          3) Track live runs from Status and logs modal (supports live streaming). 4) Inspect history or browse cross-job runs. 5)
          Tune placement via queues/affinity and worker capabilities under Workers.
        </Typography.Paragraph>
      </Card>

      <Card id="job-list" title="Jobs">
        <JobList
          jobs={jobs}
          loading={jobsQuery.isLoading}
          selectedId={selectedJobId}
          onSelect={(job) => setSelectedJobId(job._id)}
          onEdit={() => setModalVisible(true)}
        />
      </Card>

      <JobOverview />

      <WorkersMini />


      <Row gutter={[16, 16]}>
        <Col xs={24} lg={12}>
          <Card id="job-history" title="Job History">
            <JobRuns jobId={selectedJobId} />
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card id="events" title="Events">
            <EventsFeed events={events} />
          </Card>
        </Col>
      </Row>

      <Modal
        title={selectedJob ? `Edit Job – ${selectedJob.name}` : "Create Job"}
        open={modalVisible}
        onCancel={() => {
          setModalVisible(false);
          resetSelection();
        }}
        footer={null}
        width={1100}
        destroyOnClose
        bodyStyle={{ background: "#0f172a0d", borderRadius: 12 }}
      >
        <JobForm
          selectedJob={selectedJob}
          onSubmit={handleSubmit}
          onValidate={handleValidate}
          onManualRun={handleManualRun}
          onAdhocRun={handleAdhocRun}
          submitting={createMutation.isPending || updateMutation.isPending}
          validating={validating}
          statusMessage={statusMessage}
          onReset={resetSelection}
        />
        <Divider />
        <Typography.Text type="secondary">
          Jobs are persisted immediately. Closing this dialog will not discard saved changes.
        </Typography.Text>
      </Modal>
    </Space>
  );
}
