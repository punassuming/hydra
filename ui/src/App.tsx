import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { JobForm } from "./components/JobForm";
import { JobList } from "./components/JobList";
import { JobRuns } from "./components/JobRuns";
import { WorkersPanel } from "./components/WorkersPanel";
import { EventsFeed } from "./components/EventsFeed";
import { createJob, fetchJobs, JobPayload, updateJob, validateJob } from "./api/jobs";
import { useSchedulerEvents } from "./hooks/useEvents";

function App() {
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

  return (
    <div className="app-shell">
      <h1>Hydra Scheduler</h1>
      <div className="grid">
        <JobForm
          selectedJob={selectedJob}
          onSubmit={handleSubmit}
          onValidate={handleValidate}
          submitting={createMutation.isPending || updateMutation.isPending}
          validating={validating}
          statusMessage={statusMessage}
          onReset={() => {
            setSelectedJobId(null);
            setStatusMessage(undefined);
          }}
        />
        <WorkersPanel />
      </div>
      <div className="grid">
        <JobList jobs={jobs} loading={jobsQuery.isLoading} selectedId={selectedJobId} onSelect={(job) => setSelectedJobId(job._id)} />
        <JobRuns jobId={selectedJobId} />
      </div>
      <EventsFeed events={events} />
    </div>
  );
}

export default App;
