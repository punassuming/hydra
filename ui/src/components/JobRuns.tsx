import { useQuery } from "@tanstack/react-query";
import { fetchJobRuns } from "../api/jobs";

interface Props {
  jobId?: string | null;
}

export function JobRuns({ jobId }: Props) {
  const enabled = Boolean(jobId);
  const { data, isLoading } = useQuery({
    queryKey: ["job-runs", jobId],
    queryFn: () => fetchJobRuns(jobId!),
    enabled,
    refetchInterval: enabled ? 5000 : false,
  });

  return (
    <div className="panel">
      <h2>Job History</h2>
      {!jobId && <p>Select a job to view run history.</p>}
      {isLoading && jobId && <p>Loading history…</p>}
      {jobId && data && (
        <table className="table">
          <thead>
            <tr>
              <th>Status</th>
              <th>Worker</th>
              <th>Slot</th>
              <th>Attempt</th>
              <th>Queued (ms)</th>
              <th>Queued At</th>
              <th>Started</th>
              <th>Finished</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody>
            {data.slice().reverse().map((run) => (
              <tr key={run._id}>
                <td>{run.status}</td>
                <td>{run.worker_id ?? "-"}</td>
                <td>{run.slot ?? "-"}</td>
                <td>{run.attempt ?? "-"}</td>
                <td>{run.queue_latency_ms?.toFixed(0) ?? "-"}</td>
                <td>{run.scheduled_ts ? new Date(run.scheduled_ts).toLocaleTimeString() : "-"}</td>
                <td>{run.start_ts ? new Date(run.start_ts).toLocaleTimeString() : "-"}</td>
                <td>{run.end_ts ? new Date(run.end_ts).toLocaleTimeString() : "-"}</td>
                <td>{run.completion_reason ?? "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
