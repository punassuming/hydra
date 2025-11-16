import { useQuery } from "@tanstack/react-query";
import { fetchWorkers } from "../api/jobs";

export function WorkersPanel() {
  const { data } = useQuery({
    queryKey: ["workers"],
    queryFn: fetchWorkers,
    refetchInterval: 5000,
  });

  return (
    <div className="panel">
      <h2>Workers</h2>
      <table className="table">
        <thead>
          <tr>
            <th>ID</th>
            <th>OS</th>
            <th>Tags</th>
            <th>Concurrency</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {(data ?? []).map((worker) => (
            <tr key={worker.worker_id}>
              <td>{worker.worker_id}</td>
              <td>{worker.os}</td>
              <td>{worker.tags.join(", ") || "-"}</td>
              <td>
                {worker.current_running}/{worker.max_concurrency}
              </td>
              <td>{worker.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
