import { JobDefinition } from "../types";

interface Props {
  jobs?: JobDefinition[];
  onSelect: (job: JobDefinition) => void;
  selectedId?: string | null;
  loading?: boolean;
}

export function JobList({ jobs, onSelect, selectedId, loading }: Props) {
  return (
    <div className="panel">
      <h2>Jobs</h2>
      {loading && <p>Loading jobs…</p>}
      <table className="table">
        <thead>
          <tr>
            <th>Name</th>
            <th>User</th>
            <th>Executor</th>
            <th>Retries</th>
            <th>Updated</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {(jobs ?? []).map((job) => (
            <tr key={job._id} style={{ background: job._id === selectedId ? "#e0f2fe" : "transparent" }}>
              <td>{job.name}</td>
              <td>{job.user}</td>
              <td>
                <span className="pill">{job.executor.type}</span>
              </td>
              <td>{job.retries}</td>
              <td>{new Date(job.updated_at).toLocaleString()}</td>
              <td>
                <button type="button" onClick={() => onSelect(job)} style={{ backgroundColor: "#1d4ed8" }}>
                  Edit
                </button>
              </td>
            </tr>
          ))}
          {!loading && (jobs?.length ?? 0) === 0 && (
            <tr>
              <td colSpan={6}>No jobs yet.</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
