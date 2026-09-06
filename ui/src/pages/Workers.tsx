import { useMemo, useState } from "react";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { Card, Col, Progress, Row, Space, Statistic, Table, Tag, Tooltip, Typography, Button, Popconfirm, message, List, Tabs } from "antd";
import { PlusOutlined } from "@ant-design/icons";
import { detachWorker, fetchHistory, fetchWorkerOperations, fetchWorkers } from "../api/jobs";
import { WorkerInfo } from "../types";
import { apiClient } from "../api/client";
import { useNavigate } from "react-router-dom";
import { useActiveDomain } from "../context/ActiveDomainContext";
import { WorkerSetupDrawer } from "../components/WorkerSetupDrawer";

function connectivityTag(status?: string) {
  const normalized = status === "online" ? "online" : "offline";
  return <Tag color={normalized === "online" ? "green" : "volcano"}>{normalized}</Tag>;
}

function dispatchTag(state?: string) {
  const normalized = state === "draining" ? "draining" : state === "online" ? "online" : "offline";
  const color = normalized === "online" ? "green" : normalized === "draining" ? "gold" : "default";
  return <Tag color={color}>{normalized}</Tag>;
}

export function WorkersPage() {
  const queryClient = useQueryClient();
  const { domain } = useActiveDomain();
  const [setupDrawerOpen, setSetupDrawerOpen] = useState(false);
  const { data, isLoading } = useQuery({ queryKey: ["workers", domain], queryFn: fetchWorkers, refetchInterval: 5000 });
  const historyQuery = useQuery({ queryKey: ["history", domain], queryFn: () => fetchHistory(), refetchInterval: 5000 });
  const navigate = useNavigate();
  const setStateMutation = useMutation({
    mutationFn: ({ workerId, state }: { workerId: string; state: string }) =>
      apiClient.post(`/workers/${workerId}/state`, { state }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["workers", domain] }),
  });
  const detachMutation = useMutation({
    mutationFn: ({ workerId, force }: { workerId: string; force?: boolean }) => detachWorker(workerId, Boolean(force)),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["workers", domain] });
      if (result.requeued_jobs) {
        message.success(`Detached ${result.worker_id} and requeued ${result.requeued_jobs} job(s).`);
      } else {
        message.success(`Detached ${result.worker_id}.`);
      }
    },
    onError: (err: unknown) => {
      message.error(err instanceof Error ? err.message : "Failed to detach worker");
    },
  });

  const columns = [
    {
      title: "Worker",
      key: "worker",
      render: (_: unknown, record: WorkerInfo) => (
        <Space direction="vertical" size={2}>
          <Typography.Text strong>{record.worker_id}</Typography.Text>
          <Typography.Text type="secondary">
            {record.domain ?? "prod"} | {record.hostname || "-"} | {record.ip || "-"}
          </Typography.Text>
          <Typography.Text type="secondary">
            {record.os || "-"} | {record.deployment_type || "-"} | subnet {record.subnet || "-"}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: "Affinity & Capabilities",
      key: "capabilities",
      render: (_: unknown, record: WorkerInfo) => (
        <Space direction="vertical" size={4}>
          <div>{(record.tags ?? []).length ? (record.tags ?? []).map((tag) => <Tag key={tag}>{tag}</Tag>) : <Typography.Text type="secondary">No tags</Typography.Text>}</div>
          <div>{(record.shells ?? []).length ? (record.shells ?? []).map((s) => <Tag key={s} color="blue">{s}</Tag>) : <Typography.Text type="secondary">No shells</Typography.Text>}</div>
          <div>{(record.capabilities ?? []).length ? (record.capabilities ?? []).map((c) => <Tag key={c} color="cyan">{c}</Tag>) : <Typography.Text type="secondary">No capabilities</Typography.Text>}</div>
          <Typography.Text type="secondary">
            Allowed: {(record.allowed_users ?? []).length ? (record.allowed_users ?? []).join(", ") : "any"}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: "Runtime",
      key: "runtime",
      render: (_: unknown, record: WorkerInfo) => (
        <Space size={2} direction="vertical">
          <Typography.Text type="secondary">Python {record.python_version ?? "-"} | CPU {record.cpu_count ?? "-"} | User {record.run_user ?? "-"}</Typography.Text>
          <Typography.Text type="secondary">
            Mem {record.memory_rss_mb != null ? `${record.memory_rss_mb.toFixed(1)} MB` : "-"}
            {record.memory_rss_mb_max_30m != null ? ` (max ${record.memory_rss_mb_max_30m.toFixed(1)} MB)` : ""}
          </Typography.Text>
          <Typography.Text type="secondary">
            Proc {record.process_count ?? "-"}
            {record.process_count_max_30m != null ? ` (max ${record.process_count_max_30m})` : ""} | Load{" "}
            {record.load_1m != null ? record.load_1m.toFixed(2) : "-"} / {record.load_5m != null ? record.load_5m.toFixed(2) : "-"}
          </Typography.Text>
          <Typography.Text type="secondary">
            Running users: {(record.running_users ?? []).length ? (record.running_users ?? []).join(", ") : "-"}
          </Typography.Text>
          <Typography.Text type="secondary">
            Heartbeat: {record.last_heartbeat ? new Date(record.last_heartbeat * 1000).toLocaleTimeString() : "-"}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: "Saturation",
      key: "concurrency",
      render: (_: unknown, record: WorkerInfo) => {
        const max = Math.max(record.max_concurrency ?? 1, 1);
        const runningCount = record.current_running ?? 0;
        const percent = Math.round((runningCount / max) * 100);
        return (
        <Tooltip title={`Running ${runningCount} of ${max}${runningCount > max ? " (over quota via bypass jobs)" : ""}`}>
          <div>
            <div style={{ marginBottom: 4 }}>
              {runningCount}/{max}
            </div>
            <Progress
              percent={Math.min(percent, 100)}
              size="small"
              status={runningCount > max ? "exception" : "active"}
              showInfo={false}
            />
          </div>
        </Tooltip>
      )},
    },
    {
      title: "Dispatch",
      key: "state",
      render: (_: unknown, record: WorkerInfo) => (
        <Space direction="vertical" size={4}>
          <Space>
            {connectivityTag(record.connectivity_status ?? record.status)}
            {dispatchTag(record.dispatch_status ?? record.state)}
          </Space>
          <Space wrap>
            <Button size="small" onClick={(e) => { e.stopPropagation(); setStateMutation.mutate({ workerId: record.worker_id, state: "online" }); }}>
            Online
            </Button>
            <Button size="small" onClick={(e) => { e.stopPropagation(); setStateMutation.mutate({ workerId: record.worker_id, state: "draining" }); }}>
            Drain
            </Button>
            <Button size="small" onClick={(e) => { e.stopPropagation(); setStateMutation.mutate({ workerId: record.worker_id, state: "offline" }); }}>
            Offline
            </Button>
            {(record.connectivity_status ?? record.status) === "offline" && (
              <Popconfirm
                title="Detach offline worker?"
                description="Removes this offline worker record from scheduler view."
                okText="Detach"
                onConfirm={(e) => {
                  e?.stopPropagation();
                  detachMutation.mutate({ workerId: record.worker_id });
                }}
                onCancel={(e) => e?.stopPropagation()}
              >
                <Button
                  size="small"
                  danger
                  loading={detachMutation.isPending}
                  onClick={(e) => e.stopPropagation()}
                >
                  Detach
                </Button>
              </Popconfirm>
            )}
          </Space>
          <Typography.Text type="secondary">
            Running jobs: {(record.running_jobs ?? []).length}
          </Typography.Text>
        </Space>
      ),
    },
  ];
  const workers = data ?? [];
  const onlineWorkers = workers.filter((w) => (w.connectivity_status ?? w.status) === "online");
  const workerIds = useMemo(() => workers.map((w) => w.worker_id), [workers]);
  const operationsQueries = useQueries({
    queries: workerIds.map((workerId) => ({
      queryKey: ["worker-operations", domain, workerId],
      queryFn: () => fetchWorkerOperations(workerId, 50),
      enabled: Boolean(workerId),
      refetchInterval: 8000,
    })),
  });
  const operationsLoading = operationsQueries.some((q) => q.isLoading);
  const businessEvents = useMemo(() => {
    const rows: Array<{ ts: number; worker_id: string; type: string; message: string }> = [];
    operationsQueries.forEach((q, idx) => {
      const workerId = workerIds[idx];
      const events = q.data?.events ?? [];
      events.forEach((event) => {
        rows.push({
          ts: Number(event.ts || 0),
          worker_id: workerId,
          type: event.type || "event",
          message: event.message || "",
        });
      });
    });
    rows.sort((a, b) => b.ts - a.ts);
    return rows.slice(0, 120);
  }, [operationsQueries, workerIds]);

  const executionWindowSeconds = 24 * 3600;
  const executionRows = useMemo(() => {
    const now = Date.now();
    const windowStartMs = now - executionWindowSeconds * 1000;
    const runs = (historyQuery.data?.items ?? []).filter((run) => run.worker_id);
    return runs
      .map((run) => {
        const startMs = run.start_ts ? new Date(run.start_ts).getTime() : undefined;
        const endMsRaw = run.end_ts ? new Date(run.end_ts).getTime() : undefined;
        if (!startMs || Number.isNaN(startMs)) return null;
        const endMs = endMsRaw && !Number.isNaN(endMsRaw) ? endMsRaw : now;
        if (endMs < windowStartMs) return null;
        return {
          run_id: run._id,
          job_id: run.job_id,
          worker_id: run.worker_id as string,
          status: run.status,
          startMs,
          endMs,
        };
      })
      .filter((row): row is { run_id: string; job_id: string; worker_id: string; status: string; startMs: number; endMs: number } => Boolean(row))
      .sort((a, b) => a.startMs - b.startMs);
  }, [historyQuery.data]);

  const executionWorkers = useMemo(() => {
    const withRuns = Array.from(new Set(executionRows.map((r) => r.worker_id)));
    const preferred = onlineWorkers.map((w) => w.worker_id);
    return Array.from(new Set([...preferred, ...withRuns]));
  }, [executionRows, onlineWorkers]);

  const formatDuration = (ms: number) => {
    const totalMinutes = Math.max(0, Math.round(ms / 60000));
    const hours = Math.floor(totalMinutes / 60);
    const minutes = totalMinutes % 60;
    return `${hours}h ${minutes}m`;
  };

  const online = workers.filter((w) => (w.connectivity_status ?? w.status) === "online").length;
  const totalCapacity = workers.reduce((sum, w) => sum + (w.max_concurrency ?? 0), 0);
  const running = workers.reduce((sum, w) => sum + (w.current_running ?? 0), 0);
  const avgMemory = workers.length
    ? workers.reduce((sum, w) => sum + (w.memory_rss_mb ?? 0), 0) / workers.length
    : 0;
  const avgLoad1m = workers.length
    ? workers.reduce((sum, w) => sum + (w.load_1m ?? 0), 0) / workers.length
    : 0;
  const overQuotaWorkers = workers.filter((w) => (w.current_running ?? 0) > (w.max_concurrency ?? 0)).length;

  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
        <div>
          <Typography.Title level={3} style={{ marginBottom: 0 }}>
            Worker Capabilities
          </Typography.Title>
          <Typography.Text type="secondary">
            Inspect deployments, advertised runtimes, and placement hints to design new affinities.
          </Typography.Text>
        </div>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => setSetupDrawerOpen(true)}
        >
          Connect Worker
        </Button>
      </div>
      <WorkerSetupDrawer open={setupDrawerOpen} onClose={() => setSetupDrawerOpen(false)} />
      <Row gutter={16}>
        <Col xs={24} md={6}>
          <Card>
            <Statistic title="Workers Online" value={online} suffix={`/ ${workers.length}`} />
          </Card>
        </Col>
        <Col xs={24} md={6}>
          <Card>
            <Statistic title="Running Tasks" value={running} suffix={`/ ${totalCapacity}`} />
          </Card>
        </Col>
        <Col xs={24} md={6}>
          <Card>
            <Statistic title="Avg Memory RSS" value={avgMemory.toFixed(1)} suffix="MB" />
          </Card>
        </Col>
        <Col xs={24} md={6}>
          <Card>
            <Statistic title="Avg Load (1m)" value={avgLoad1m.toFixed(2)} suffix={`| ${overQuotaWorkers} over quota`} />
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card>
            <Statistic title="Unique Tags" value={new Set(workers.flatMap((w) => w.tags ?? [])).size} />
          </Card>
        </Col>
      </Row>
      <Card>
        <Table
          dataSource={workers.map((w) => ({ ...w, key: w.worker_id }))}
          columns={columns}
          loading={isLoading}
          pagination={{ pageSize: 10 }}
          size="small"
          onRow={(record) => ({
            onClick: () => navigate(`/workers/${record.worker_id}`),
            style: { cursor: "pointer" },
          })}
        />
      </Card>
      <Card title="Execution / Business Timeline">
        <Tabs
          items={[
            {
              key: "execution",
              label: "Execution Timeline",
              children: (
                <Space direction="vertical" style={{ width: "100%" }} size={8}>
                  <Typography.Text type="secondary">
                    Busy/idle over the last 24 hours across all workers.
                  </Typography.Text>
                  {executionWorkers.length === 0 ? (
                    <Typography.Text type="secondary">No worker timelines to display.</Typography.Text>
                  ) : (
                    executionWorkers.map((wid) => {
                      const laneRuns = executionRows.filter((r) => r.worker_id === wid);
                      const nowMs = Date.now();
                      const windowStartMs = nowMs - executionWindowSeconds * 1000;
                      const spanMs = executionWindowSeconds * 1000;
                      const busyIntervals = laneRuns
                        .map((run) => ({
                          startMs: Math.max(run.startMs, windowStartMs),
                          endMs: Math.min(run.endMs, nowMs),
                        }))
                        .filter((x) => x.endMs > x.startMs)
                        .sort((a, b) => a.startMs - b.startMs)
                        .reduce<Array<{ startMs: number; endMs: number }>>((acc, current) => {
                          const last = acc[acc.length - 1];
                          if (!last || current.startMs > last.endMs) {
                            acc.push({ ...current });
                          } else {
                            last.endMs = Math.max(last.endMs, current.endMs);
                          }
                          return acc;
                        }, []);
                      const segments: Array<{ kind: "busy" | "idle"; startMs: number; endMs: number }> = [];
                      let cursor = windowStartMs;
                      busyIntervals.forEach((interval) => {
                        if (interval.startMs > cursor) {
                          segments.push({ kind: "idle", startMs: cursor, endMs: interval.startMs });
                        }
                        segments.push({ kind: "busy", startMs: interval.startMs, endMs: interval.endMs });
                        cursor = Math.max(cursor, interval.endMs);
                      });
                      if (cursor < nowMs) {
                        segments.push({ kind: "idle", startMs: cursor, endMs: nowMs });
                      }
                      if (!segments.length) {
                        segments.push({ kind: "idle", startMs: windowStartMs, endMs: nowMs });
                      }
                      const busyMs = busyIntervals.reduce((sum, interval) => sum + (interval.endMs - interval.startMs), 0);
                      const idleMs = Math.max(0, spanMs - busyMs);
                      return (
                        <div key={wid} style={{ display: "flex", gap: 8, alignItems: "center" }}>
                          <div style={{ width: 250, fontSize: 12, color: "#475569" }}>
                            <div>{wid}</div>
                            <div>
                              Busy {formatDuration(busyMs)} | Idle {formatDuration(idleMs)}
                            </div>
                          </div>
                          <div
                            style={{
                              position: "relative",
                              flex: 1,
                              height: 26,
                              borderRadius: 6,
                              border: "1px solid rgba(148, 163, 184, 0.35)",
                              background: "rgba(148, 163, 184, 0.08)",
                            }}
                          >
                            {segments.map((segment, idx) => {
                              const left = ((segment.startMs - windowStartMs) / spanMs) * 100;
                              const width = Math.max(((segment.endMs - segment.startMs) / spanMs) * 100, 0.4);
                              const isBusy = segment.kind === "busy";
                              return (
                                <Tooltip
                                  key={`${wid}-${idx}`}
                                  title={`${isBusy ? "Busy" : "Idle"} | ${new Date(segment.startMs).toLocaleString()} - ${new Date(segment.endMs).toLocaleString()}`}
                                >
                                  <div
                                    style={{
                                      position: "absolute",
                                      left: `${left}%`,
                                      width: `${width}%`,
                                      top: 4,
                                      bottom: 4,
                                      borderRadius: 5,
                                      minWidth: 2,
                                      background: isBusy ? "#16a34a" : "rgba(148, 163, 184, 0.28)",
                                      border: isBusy ? "1px solid rgba(22, 163, 74, 0.7)" : "1px solid rgba(148, 163, 184, 0.45)",
                                      opacity: 0.95,
                                    }}
                                  />
                                </Tooltip>
                              );
                            })}
                          </div>
                        </div>
                      );
                    })
                  )}
                </Space>
              ),
            },
            {
              key: "business",
              label: "Business Timeline",
              children: (
                <List
                  loading={operationsLoading}
                  dataSource={businessEvents}
                  locale={{ emptyText: "No recent worker operation events." }}
                  renderItem={(event) => (
                    <List.Item>
                      <Space wrap>
                        <Typography.Text type="secondary">
                          {new Date(event.ts * 1000).toLocaleString()}
                        </Typography.Text>
                        <Tag>{event.worker_id}</Tag>
                        <Tag color="blue">{event.type}</Tag>
                        <Typography.Text>{event.message}</Typography.Text>
                      </Space>
                    </List.Item>
                  )}
                />
              ),
            },
          ]}
        />
      </Card>
    </Space>
  );
}
