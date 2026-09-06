import { Drawer, Space, Typography } from "antd";
import { Link } from "react-router-dom";
import { JobRun } from "../types";
import { StatusBadge } from "./StatusBadge";
import { LogViewer } from "./LogViewer";
import { FailureInsight } from "./FailureInsight";
import { useQuery } from "@tanstack/react-query";
import { fetchRun } from "../api/jobs";
import { useActiveDomain } from "../context/ActiveDomainContext";

interface Props { run?: JobRun; runId?: string; open: boolean; onClose: () => void; }

export function RunInspector({ run: providedRun, runId, open, onClose }: Props) {
  const { domain } = useActiveDomain();
  const { data } = useQuery({ queryKey: ["run", domain, runId], queryFn: () => fetchRun(runId!), enabled: open && Boolean(runId) && !providedRun });
  const run = providedRun ?? data;
  return <Drawer title="Run inspector" width={760} open={open} onClose={onClose} destroyOnClose>
    {run ? <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Space wrap>
        <StatusBadge status={run.status} />
        <Typography.Text type="secondary">Run {run._id}</Typography.Text>
        <Link to={`/jobs/${run.job_id}`}>Open job</Link>
        {run.worker_id && <Link to={`/workers/${run.worker_id}`}>Open worker</Link>}
      </Space>
      <Typography.Text>Started: {run.start_ts ? new Date(run.start_ts).toLocaleString() : "-"} · Finished: {run.end_ts ? new Date(run.end_ts).toLocaleString() : "-"} · Duration: {typeof run.duration === "number" ? `${run.duration.toFixed(1)}s` : "-"}</Typography.Text>
      <LogViewer stdout={run.stdout_tail ?? run.stdout} stderr={run.stderr_tail ?? run.stderr} maxHeight={420} />
      <FailureInsight runId={run._id} stdout={run.stdout || ""} stderr={run.stderr || ""} exitCode={run.returncode || 1} />
    </Space> : <Typography.Text type="secondary">No run selected.</Typography.Text>}
  </Drawer>;
}
