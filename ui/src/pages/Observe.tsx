import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Card, Space, Typography, Button, Progress, Table, Tag, Modal, Tabs, Input, Select, Spin } from "antd";
import { fetchJobOverview, runJobNow, fetchHistory, fetchJobs, fetchWorkers } from "../api/jobs";
import { JobOverview, JobRun, WorkerInfo } from "../types";
import { useActiveDomain } from "../context/ActiveDomainContext";
import { StatusBadge } from "../components/StatusBadge";
import { LogViewer } from "../components/LogViewer";
import { FailureInsight } from "../components/FailureInsight";
import { useTheme } from "../theme";
import {
  BarChartOutlined,
  HistoryOutlined,
  TableOutlined,
} from "@ant-design/icons";

function StatusTab() {
  const queryClient = useQueryClient();
  const { domain } = useActiveDomain();
  const { colors } = useTheme();
  const overviewQuery = useQuery({ queryKey: ["job-overview", domain], queryFn: fetchJobOverview, refetchInterval: 5000 });
  const [searchText, setSearchText] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");

  const runNow = useMutation({
    mutationFn: (jobId: string) => runJobNow(jobId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["job-overview", domain] });
    },
  });

  const renderRunStrip = (runs: JobRun[] | undefined) => {
    const recent = (runs ?? []).slice(0, 10);
    if (!recent.length) return <Typography.Text type="secondary">No runs yet</Typography.Text>;
    const color = (status?: string) =>
      status === "success" ? colors.success : status === "running" ? colors.info : colors.warning;
    return (
      <Space size={6}>
        {recent.map((run, idx) => (
          <div
            key={run._id ?? idx}
            title={`${run.status} · ${run.start_ts ? new Date(run.start_ts).toLocaleString() : "n/a"}`}
            style={{
              width: 12,
              height: 12,
              borderRadius: 3,
              background: color(run.status),
              opacity: idx === 0 ? 1 : 0.7,
            }}
          />
        ))}
      </Space>
    );
  };

  const renderDurationSpark = (runs: JobRun[] | undefined) => {
    const durations = (runs ?? [])
      .map((r) => (typeof r.duration === "number" ? r.duration : null))
      .filter((d): d is number => d !== null);
    if (!durations.length) return <Typography.Text type="secondary">No duration data</Typography.Text>;
    const max = Math.max(...durations, 1);
    return (
      <div style={{ display: "flex", alignItems: "flex-end", gap: 4, height: 40 }}>
        {durations.map((d, idx) => (
          <div
            key={`${d}-${idx}`}
            style={{
              width: 12,
              height: Math.max(6, (d / max) * 36),
              background: colors.primary,
              borderRadius: 4,
              opacity: 0.8,
            }}
            title={`~${d.toFixed(1)}s`}
          />
        ))}
      </div>
    );
  };

  const overview = overviewQuery.data ?? [];
  const statusOptions = useMemo(() => {
    const set = new Set<string>();
    for (const job of overview) {
      set.add((job.last_run?.status ?? "never").toLowerCase());
    }
    return Array.from(set).sort();
  }, [overview]);

  const filteredOverview = useMemo(() => {
    const needle = searchText.trim().toLowerCase();
    return overview.filter((job) => {
      const lastStatus = (job.last_run?.status ?? "never").toLowerCase();
      if (statusFilter !== "all" && lastStatus !== statusFilter) {
        return false;
      }
      if (!needle) {
        return true;
      }
      const haystack = [job.name, job.job_id, job.schedule_mode, ...(job.tags ?? [])]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(needle);
    });
  }, [overview, searchText, statusFilter]);

  return (
    <Card
      title="Job Status"
      extra={
        <Space wrap>
          <Typography.Text type="secondary">Run health across all jobs.</Typography.Text>
          <Input.Search
            allowClear
            placeholder="Filter by job, id, tag"
            style={{ width: 240 }}
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
          />
          <Select
            value={statusFilter}
            style={{ width: 150 }}
            onChange={setStatusFilter}
            options={[
              { label: "All statuses", value: "all" },
              ...statusOptions.map((status) => ({ label: status, value: status })),
            ]}
          />
        </Space>
      }
    >
      <Table
        rowKey="job_id"
        loading={overviewQuery.isLoading}
        dataSource={filteredOverview}
        pagination={{ pageSize: 10 }}
        columns={[
          {
            title: "Job",
            dataIndex: "name",
            key: "name",
            render: (_: unknown, job) => {
              const last = job.last_run;
              return (
                <Space>
                  <Typography.Text strong>{job.name}</Typography.Text>
                  <Tag color="default">{job.schedule_mode === "immediate" ? "manual" : job.schedule_mode}</Tag>
                  {last && <StatusBadge status={last.status} />}
                </Space>
              );
            },
          },
          {
            title: "Success / Failed / Total / Queued",
            key: "counts",
            render: (_: unknown, job) => (
              <Space direction="vertical" size={4}>
                <div>
                  {job.success_runs} / {job.failed_runs} / {job.total_runs} / {job.queued_runs ?? 0}
                </div>
                <Progress
                  percent={job.total_runs ? Math.round((job.success_runs / job.total_runs) * 100) : 0}
                  size="small"
                  status="active"
                />
              </Space>
            ),
          },
          {
            title: "Recent Runs",
            key: "recent",
            render: (_: unknown, job) => renderRunStrip(job.recent_runs),
          },
          {
            title: "Durations",
            key: "durations",
            render: (_: unknown, job) => renderDurationSpark(job.recent_runs),
          },
          {
            title: "Last Run",
            key: "last",
            render: (_: unknown, job) => {
              const last = job.last_run as JobRun | undefined;
              if (!last) return "-";
              return (
                <Space direction="vertical" size={2}>
                  <div>{last.start_ts ? new Date(last.start_ts).toLocaleString() : "-"}</div>
                  {typeof last.duration === "number" && <div>{last.duration.toFixed(1)}s</div>}
                </Space>
              );
            },
          },
          {
            title: "",
            key: "actions",
            render: (_: unknown, job) => (
              <Button size="small" onClick={() => runNow.mutate(job.job_id)} loading={runNow.isPending}>
                Run Now
              </Button>
            ),
          },
        ]}
      />
    </Card>
  );
}

function HistoryTab() {
  const { domain } = useActiveDomain();
  const [searchText, setSearchText] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const { data, isLoading } = useQuery({
    queryKey: ["history", domain],
    queryFn: fetchHistory,
    refetchInterval: 5000,
  });
  const jobsQuery = useQuery({
    queryKey: ["jobs", domain],
    queryFn: () => fetchJobs(),
    refetchInterval: 10000,
  });
  const workersQuery = useQuery({
    queryKey: ["workers", domain],
    queryFn: fetchWorkers,
    refetchInterval: 5000,
  });
  const [logModal, setLogModal] = useState<{ visible: boolean; run?: JobRun }>({ visible: false });

  const jobsById = useMemo(() => {
    const map = new Map<string, string>();
    for (const job of jobsQuery.data ?? []) {
      map.set(job._id, job.name);
    }
    return map;
  }, [jobsQuery.data]);

  const workersById = useMemo(() => {
    const map = new Map<string, WorkerInfo>();
    for (const worker of workersQuery.data ?? []) {
      map.set(worker.worker_id, worker);
    }
    return map;
  }, [workersQuery.data]);

  const statusOptions = useMemo(() => {
    const set = new Set<string>();
    for (const run of data ?? []) {
      set.add((run.status ?? "unknown").toLowerCase());
    }
    return Array.from(set).sort();
  }, [data]);

  const filteredRuns = useMemo(() => {
    const needle = searchText.trim().toLowerCase();
    return (data ?? []).filter((run) => {
      const status = (run.status ?? "unknown").toLowerCase();
      if (statusFilter !== "all" && status !== statusFilter) {
        return false;
      }
      if (!needle) {
        return true;
      }
      const jobName = jobsById.get(run.job_id) ?? "";
      const worker = run.worker_id ? workersById.get(run.worker_id) : undefined;
      const haystack = [
        run.job_id,
        jobName,
        run.user,
        run.domain,
        run.worker_id,
        worker?.hostname,
        worker?.ip,
        run.status,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(needle);
    });
  }, [data, jobsById, searchText, statusFilter, workersById]);

  const columns = [
    {
      title: "Job",
      dataIndex: "job_id",
      key: "job_id",
      render: (jobId: string) => (
        <Space direction="vertical" size={0}>
          <Typography.Text strong>{jobsById.get(jobId) ?? jobId}</Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>{jobId}</Typography.Text>
        </Space>
      ),
    },
    { title: "User", dataIndex: "user", key: "user" },
    { title: "Domain", dataIndex: "domain", key: "domain", render: (value?: string) => value ?? "prod" },
    {
      title: "Status",
      dataIndex: "status",
      key: "status",
      render: (status: string) => <StatusBadge status={status} />,
    },
    {
      title: "Worker",
      dataIndex: "worker_id",
      key: "worker_id",
      render: (workerId?: string) => {
        if (!workerId) return "-";
        const worker = workersById.get(workerId);
        if (!worker) {
          return <Typography.Text>{workerId}</Typography.Text>;
        }
        return (
          <Space direction="vertical" size={0}>
            <Typography.Text strong>{worker.worker_id}</Typography.Text>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {worker.hostname ?? "unknown-host"} · {worker.ip ?? "n/a"}
            </Typography.Text>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {worker.connectivity_status ?? worker.status} / {worker.dispatch_status ?? worker.state ?? "unknown"}
            </Typography.Text>
          </Space>
        );
      },
    },
    {
      title: "Started",
      dataIndex: "start_ts",
      key: "start_ts",
      render: (value?: string) => (value ? new Date(value).toLocaleString() : "-"),
    },
    {
      title: "Finished",
      dataIndex: "end_ts",
      key: "end_ts",
      render: (value?: string) => (value ? new Date(value).toLocaleString() : "-"),
    },
    {
      title: "Logs",
      key: "logs",
      render: (_: unknown, record: JobRun) => (
        <Typography.Link onClick={() => setLogModal({ visible: true, run: record })}>View Logs</Typography.Link>
      ),
    },
  ];

  const runs = filteredRuns.map((run) => ({ ...run, key: run._id }));

  return (
    <>
      <Card
        title="Run History"
        extra={
          <Space wrap>
            <Typography.Text type="secondary">All runs across jobs.</Typography.Text>
            <Input.Search
              allowClear
              placeholder="Filter by job, worker, user"
              style={{ width: 240 }}
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
            />
            <Select
              value={statusFilter}
              style={{ width: 150 }}
              onChange={setStatusFilter}
              options={[
                { label: "All statuses", value: "all" },
                ...statusOptions.map((status) => ({ label: status, value: status })),
              ]}
            />
          </Space>
        }
      >
        <Table dataSource={runs} columns={columns} loading={isLoading} size="small" pagination={{ pageSize: 10 }} />
      </Card>
      <Modal open={logModal.visible} onCancel={() => setLogModal({ visible: false })} footer={null} width={1000} title="Run Logs">
        {logModal.run ? (
          <Space direction="vertical" style={{ width: "100%" }}>
            <Space>
              <StatusBadge status={logModal.run.status} />
              <Typography.Text type="secondary">Run ID: {logModal.run._id}</Typography.Text>
              {logModal.run.worker_id && <Typography.Text type="secondary">Worker: {logModal.run.worker_id}</Typography.Text>}
            </Space>
            <Typography.Text>
              Started: {logModal.run.start_ts ? new Date(logModal.run.start_ts).toLocaleString() : "-"} · 
              Finished: {logModal.run.end_ts ? new Date(logModal.run.end_ts).toLocaleString() : "-"} · 
              Duration: {typeof logModal.run.duration === "number" ? `${logModal.run.duration.toFixed(1)}s` : "-"}
            </Typography.Text>
            <LogViewer
              stdout={logModal.run.stdout_tail ?? logModal.run.stdout}
              stderr={logModal.run.stderr_tail ?? logModal.run.stderr}
              maxHeight={400}
            />
            <FailureInsight
              runId={logModal.run._id}
              stdout={logModal.run.stdout || ""}
              stderr={logModal.run.stderr || ""}
              exitCode={logModal.run.returncode || 1}
            />
          </Space>
        ) : (
          <Typography.Text type="secondary">No logs available.</Typography.Text>
        )}
      </Modal>
    </>
  );
}

const GRID_TICKS = 30;

function statusToCellClass(status: string | undefined): string {
  if (!status) return "gcell-skipped";
  switch (status.toLowerCase()) {
    case "success": return "gcell-success";
    case "failed":
    case "error": return "gcell-failed";
    case "running": return "gcell-running";
    case "queued":
    case "pending": return "gcell-queued";
    default: return "gcell-skipped";
  }
}

function GridTab() {
  const { domain } = useActiveDomain();
  const overviewQuery = useQuery({
    queryKey: ["job-overview", domain],
    queryFn: fetchJobOverview,
    refetchInterval: 10000,
  });

  const jobs: JobOverview[] = overviewQuery.data ?? [];

  const tickLabels = Array.from({ length: GRID_TICKS }, (_, i) => {
    const tick = GRID_TICKS - i;
    return tick % 5 === 0 ? `t-${tick}` : "";
  });

  return (
    <Card
      title="Task Instance Grid — All Jobs"
      extra={
        <div className="grid-tab-legend">
          <span className="grid-tab-legend-item"><span className="gcell gcell-success" /> ok</span>
          <span className="grid-tab-legend-item"><span className="gcell gcell-failed" /> fail</span>
          <span className="grid-tab-legend-item"><span className="gcell gcell-running" /> run</span>
          <span className="grid-tab-legend-item"><span className="gcell gcell-skipped" /> no data</span>
        </div>
      }
    >
      {overviewQuery.isLoading ? (
        <div style={{ textAlign: "center", padding: 32 }}>
          <Spin size="large" />
        </div>
      ) : jobs.length === 0 ? (
        <Typography.Text type="secondary">No jobs found.</Typography.Text>
      ) : (
        <>
          <Typography.Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 12 }}>
            Last {GRID_TICKS} run slots across all jobs — newest on the right.
          </Typography.Text>
          <div className="grid-tab-wrap">
            <table className="grid-tab-table">
              <thead>
                <tr>
                  <th className="grid-tab-label-cell" style={{ fontWeight: 500, fontSize: 11, color: "var(--v2-text-3)" }}>
                    Job
                  </th>
                  {tickLabels.map((label, j) => (
                    <th key={j} className="grid-tab-head-cell">{label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {jobs.map((job) => {
                  const runs = (job.recent_runs ?? []).slice().reverse();
                  const cells = Array.from({ length: GRID_TICKS }, (_, i) => {
                    const run = runs[i];
                    return run ? run.status : undefined;
                  });
                  return (
                    <tr key={job.job_id}>
                      <td className="grid-tab-label-cell">
                        <span title={job.job_id}>{job.name}</span>
                      </td>
                      {cells.map((status, j) => (
                        <td key={j} style={{ padding: 0 }}>
                          <span
                            className={`gcell ${statusToCellClass(status)}`}
                            title={status ?? "no data"}
                          />
                        </td>
                      ))}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Card>
  );
}

export function ObservePage() {
  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <Tabs
        defaultActiveKey="status"
        items={[
          {
            key: "status",
            label: (
              <span>
                <BarChartOutlined /> Status
              </span>
            ),
            children: <StatusTab />,
          },
          {
            key: "grid",
            label: (
              <span>
                <TableOutlined /> Grid
              </span>
            ),
            children: <GridTab />,
          },
          {
            key: "history",
            label: (
              <span>
                <HistoryOutlined /> History
              </span>
            ),
            children: <HistoryTab />,
          },
        ]}
      />
    </Space>
  );
}
