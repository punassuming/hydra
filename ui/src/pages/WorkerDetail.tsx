import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Card, Col, Descriptions, Row, Space, Statistic, Tag, Typography, Button, List, Slider, Tooltip } from "antd";
import { useNavigate, useParams } from "react-router-dom";
import { fetchWorkerMetrics, fetchWorkerOperations, fetchWorkers, fetchWorkerTimeline } from "../api/jobs";
import { apiClient } from "../api/client";
import { WorkerMetricPoint, WorkerOperation, WorkerTimelineData, WorkerTimelineEntry } from "../types";
import { useActiveDomain } from "../context/ActiveDomainContext";
import { RunInspector } from "../components/RunInspector";

function statusColor(status: string) {
  if (status === "success") return "#22c55e";
  if (status === "failed") return "#ef4444";
  if (status === "running") return "#3b82f6";
  return "#64748b";
}

function colorFromName(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i += 1) {
    hash = (hash * 31 + name.charCodeAt(i)) | 0;
  }
  const hue = Math.abs(hash) % 360;
  return `hsl(${hue} 70% 45%)`;
}

function opColor(opType: string) {
  if (opType.includes("fail")) return "error";
  if (opType.includes("start")) return "processing";
  if (opType.includes("state")) return "warning";
  if (opType.includes("dispatch")) return "blue";
  if (opType.includes("end") || opType.includes("result")) return "success";
  return "default";
}

function MetricLineChart({
  title,
  points,
  selector,
  unit,
  color,
}: {
  title: string;
  points: WorkerMetricPoint[];
  selector: (p: WorkerMetricPoint) => number | null | undefined;
  unit: string;
  color: string;
}) {
  const valid = points
    .map((p) => ({ ts: p.ts, v: selector(p) }))
    .filter((p): p is { ts: number; v: number } => p.v != null && Number.isFinite(p.v));
  if (!valid.length) {
    return (
      <Card size="small" title={title}>
        <Typography.Text type="secondary">No metrics yet.</Typography.Text>
      </Card>
    );
  }

  const minTs = valid[0].ts;
  const maxTs = valid[valid.length - 1].ts;
  const minV = Math.min(...valid.map((p) => p.v));
  const maxV = Math.max(...valid.map((p) => p.v));
  const spanTs = Math.max(maxTs - minTs, 1);
  const spanV = Math.max(maxV - minV, 1);

  const path = valid
    .map((p, idx) => {
      const x = 14 + ((p.ts - minTs) / spanTs) * 452;
      const y = 108 - ((p.v - minV) / spanV) * 84;
      return `${idx === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(" ");
  const latest = valid[valid.length - 1].v;

  return (
    <Card
      size="small"
      title={title}
      extra={
        <Typography.Text type="secondary">
          {latest.toFixed(2)} {unit} now
        </Typography.Text>
      }
    >
      <svg viewBox="0 0 480 120" style={{ width: "100%", height: 120 }}>
        <rect x="14" y="12" width="452" height="96" fill="rgba(148,163,184,0.08)" rx="8" />
        <path d={path} stroke={color} strokeWidth="2.5" fill="none" />
      </svg>
      <Typography.Text type="secondary">
        {new Date(minTs * 1000).toLocaleTimeString()} - {new Date(maxTs * 1000).toLocaleTimeString()}
      </Typography.Text>
    </Card>
  );
}

function WorkerTimeline({ data, onInspect }: { data?: WorkerTimelineData; onInspect: (runId: string) => void }) {
  if (!data?.entries?.length) {
    return <Typography.Text type="secondary">No worker executions in the selected window.</Typography.Text>;
  }
  const entries = data.entries;
  const maxSlot = Math.max(...entries.map((e) => Math.max(0, e.slot)), data.max_concurrency - 1);
  const laneCount = Math.max(data.max_concurrency, maxSlot + 1);
  const lanes: WorkerTimelineEntry[][] = Array.from({ length: laneCount }, () => []);
  entries.forEach((entry) => {
    lanes[Math.max(0, entry.slot)].push(entry);
  });
  const windowStart = data.window_start_ts;
  const windowEnd = data.window_end_ts;
  const span = Math.max(windowEnd - windowStart, 1);

  return (
    <Space direction="vertical" style={{ width: "100%" }} size={8}>
      <Typography.Text type="secondary">
        Lane rows 1-{data.max_concurrency} are worker quota lanes; overflow rows indicate concurrency-bypass jobs.
      </Typography.Text>
      {lanes.map((laneEntries, laneIdx) => {
        const isOverflow = laneIdx >= data.max_concurrency;
        return (
          <div key={laneIdx} style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <div style={{ width: 140, fontSize: 12, color: isOverflow ? "#dc2626" : "#475569" }}>
              {isOverflow ? `Overflow ${laneIdx - data.max_concurrency + 1}` : `Slot ${laneIdx + 1}`}
            </div>
            <div
              style={{
                position: "relative",
                flex: 1,
                height: 28,
                borderRadius: 6,
                border: "1px solid rgba(148, 163, 184, 0.35)",
                background: isOverflow ? "rgba(239, 68, 68, 0.06)" : "rgba(148, 163, 184, 0.08)",
              }}
            >
              {laneEntries.map((entry) => {
                const start = Math.max(entry.start_ts, windowStart);
                const end = Math.min(entry.end_ts, windowEnd);
                const left = ((start - windowStart) / span) * 100;
                const width = Math.max(((end - start) / span) * 100, 0.6);
                return (
                  <Tooltip
                    key={entry.run_id}
                    title={`${entry.job_name || entry.job_id} | ${entry.status} | ${new Date(entry.start_ts * 1000).toLocaleTimeString()} - ${new Date(entry.end_ts * 1000).toLocaleTimeString()}`}
                  >
                    <div
                      onClick={() => onInspect(entry.run_id)}
                      style={{
                        position: "absolute",
                        left: `${left}%`,
                        width: `${width}%`,
                        minWidth: 10,
                        top: 4,
                        bottom: 4,
                        borderRadius: 5,
                        background: colorFromName(entry.job_name || entry.job_id),
                        border: `1px solid ${statusColor(entry.status)}`,
                        opacity: entry.bypass_concurrency ? 0.75 : 0.95,
                        outline: entry.bypass_concurrency ? "2px dashed rgba(15, 23, 42, 0.25)" : "none",
                        overflow: "hidden",
                        whiteSpace: "nowrap",
                        textOverflow: "ellipsis",
                        color: "#f8fafc",
                        fontSize: 11,
                        padding: "2px 6px",
                        cursor: "pointer",
                      }}
                    >
                      {entry.job_name || entry.job_id}
                    </div>
                  </Tooltip>
                );
              })}
            </div>
          </div>
        );
      })}
      <Typography.Text type="secondary">
        {new Date(windowStart * 1000).toLocaleString()} - {new Date(windowEnd * 1000).toLocaleString()}
      </Typography.Text>
    </Space>
  );
}

export function WorkerDetailPage() {
  const { domain } = useActiveDomain();
  const { workerId } = useParams<{ workerId: string }>();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [windowMinutes, setWindowMinutes] = useState<number>(() => {
    const v =
      Number(localStorage.getItem("hydra_worker_window")) ||
      Number(localStorage.getItem("hydra_worker_metrics_window")) ||
      Number(localStorage.getItem("hydra_worker_timeline_window"));
    return Number.isFinite(v) && v > 0 ? v : 30;
  });
  const [inspectedRunId, setInspectedRunId] = useState<string>();
  const { data, isLoading } = useQuery({ queryKey: ["workers", domain], queryFn: fetchWorkers, refetchInterval: 5000 });
  const worker = data?.find((w) => w.worker_id === workerId);
  const metricsQuery = useQuery({
    queryKey: ["worker-metrics", domain, workerId, windowMinutes],
    queryFn: () => fetchWorkerMetrics(workerId!, windowMinutes),
    enabled: Boolean(workerId),
    refetchInterval: 10000,
  });
  const timelineQuery = useQuery({
    queryKey: ["worker-timeline", domain, workerId, windowMinutes],
    queryFn: () => fetchWorkerTimeline(workerId!, windowMinutes),
    enabled: Boolean(workerId),
    refetchInterval: 10000,
  });
  const operationsQuery = useQuery({
    queryKey: ["worker-operations", domain, workerId],
    queryFn: () => fetchWorkerOperations(workerId!, 50),
    enabled: Boolean(workerId),
    refetchInterval: 5000,
  });
  const metricPoints = useMemo(() => metricsQuery.data?.points ?? [], [metricsQuery.data?.points]);
  const windowMarks = useMemo(
    () => ({
      10: "10m",
      30: "30m",
      60: "60m",
      120: "120m",
      180: "180m",
      360: "360m",
    }),
    [],
  );

  useEffect(() => {
    localStorage.setItem("hydra_worker_window", String(windowMinutes));
    localStorage.setItem("hydra_worker_metrics_window", String(windowMinutes));
    localStorage.setItem("hydra_worker_timeline_window", String(windowMinutes));
  }, [windowMinutes]);

  const setStateMutation = useMutation({
    mutationFn: (state: string) => apiClient.post(`/workers/${workerId}/state`, { state }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["workers", domain] }),
  });

  if (!workerId) {
    return <Typography.Text>Please choose a worker from the list.</Typography.Text>;
  }

  if (isLoading) {
    return <Typography.Text>Loading worker…</Typography.Text>;
  }

  if (!worker) {
    return (
      <Space direction="vertical">
        <Typography.Text>Worker {workerId} not found.</Typography.Text>
        <Button onClick={() => navigate("/workers")}>Back to Workers</Button>
      </Space>
    );
  }

  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <Space align="center" wrap>
        <Typography.Title level={3} style={{ marginBottom: 0 }}>
          {worker.worker_id}
        </Typography.Title>
        <Tag color={(worker.connectivity_status ?? worker.status) === "online" ? "green" : "volcano"}>
          connectivity: {worker.connectivity_status ?? worker.status}
        </Tag>
        <Tag color={(worker.dispatch_status ?? worker.state) === "online" ? "green" : (worker.dispatch_status ?? worker.state) === "draining" ? "gold" : "default"}>
          dispatch: {worker.dispatch_status ?? worker.state ?? "offline"}
        </Tag>
        <Button onClick={() => navigate("/workers")}>Back</Button>
      </Space>

      <Row gutter={16}>
        <Col xs={24} md={8}>
          <Card>
            <Statistic title="Concurrency" value={`${worker.current_running ?? 0}/${worker.max_concurrency ?? 0}`} />
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card>
            <Statistic title="Allowed Users" value={worker.allowed_users?.length ? worker.allowed_users.join(", ") : "any"} />
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card>
            <Statistic title="Tags" value={(worker.tags ?? []).length} />
          </Card>
        </Col>
      </Row>
      <Row gutter={16}>
        <Col xs={24} md={8}>
          <Card>
            <Statistic title="Memory RSS" value={worker.memory_rss_mb != null ? `${worker.memory_rss_mb.toFixed(1)} MB` : "-"} />
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card>
            <Statistic
              title="Memory RSS Max (30m)"
              value={worker.memory_rss_mb_max_30m != null ? `${worker.memory_rss_mb_max_30m.toFixed(1)} MB` : "-"}
            />
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card>
            <Statistic
              title="Load (1m / 5m)"
              value={
                worker.load_1m != null || worker.load_5m != null
                  ? `${worker.load_1m?.toFixed(2) ?? "-"} / ${worker.load_5m?.toFixed(2) ?? "-"}`
                  : "-"
              }
            />
          </Card>
        </Col>
      </Row>

      <Card
        title="Runtime Metrics Trend"
        extra={
          <div style={{ width: 220 }}>
            <Slider
              min={10}
              max={360}
              step={null}
              marks={windowMarks}
              value={windowMinutes}
              onChange={(value) => setWindowMinutes(value as number)}
              tooltip={{ formatter: (value) => `${value}m` }}
            />
          </div>
        }
      >
        <Typography.Text type="secondary" style={{ display: "block", marginBottom: 8 }}>
          Time window applies to both runtime trends and execution timeline.
        </Typography.Text>
        <Row gutter={12}>
          <Col xs={24} xl={8}>
            <MetricLineChart title="Memory RSS" points={metricPoints} selector={(p) => p.memory_rss_mb} unit="MB" color="#0284c7" />
          </Col>
          <Col xs={24} xl={8}>
            <MetricLineChart title="Process Count" points={metricPoints} selector={(p) => p.process_count} unit="proc" color="#16a34a" />
          </Col>
          <Col xs={24} xl={8}>
            <MetricLineChart title="Load (1m)" points={metricPoints} selector={(p) => p.load_1m} unit="load" color="#f59e0b" />
          </Col>
        </Row>
      </Card>

      <Card
        title="Worker Execution Timeline"
        extra={
          <div style={{ width: 220 }}>
            <Slider
              min={10}
              max={360}
              step={null}
              marks={windowMarks}
              value={windowMinutes}
              onChange={(value) => setWindowMinutes(value as number)}
              tooltip={{ formatter: (value) => `${value}m` }}
            />
          </div>
        }
      >
        <WorkerTimeline data={timelineQuery.data} onInspect={setInspectedRunId} />
      </Card>

      <Row gutter={16}>
        <Col xs={24} md={8}>
          <Card>
            <Statistic
              title="Process Count (Now / 30m Max)"
              value={
                worker.process_count != null || worker.process_count_max_30m != null
                  ? `${worker.process_count ?? "-"} / ${worker.process_count_max_30m ?? "-"}`
                  : "-"
              }
            />
          </Card>
        </Col>
      </Row>

      <Card title="Details">
        <Descriptions bordered column={1} size="small">
          <Descriptions.Item label="Domain">{worker.domain}</Descriptions.Item>
          <Descriptions.Item label="Hostname">{worker.hostname || "-"}</Descriptions.Item>
          <Descriptions.Item label="IP">{worker.ip || "-"}</Descriptions.Item>
          <Descriptions.Item label="OS">{worker.os || "-"}</Descriptions.Item>
          <Descriptions.Item label="Deployment">{worker.deployment_type || "-"}</Descriptions.Item>
          <Descriptions.Item label="Subnet">{worker.subnet || "-"}</Descriptions.Item>
          <Descriptions.Item label="Python">{worker.python_version || "-"}</Descriptions.Item>
          <Descriptions.Item label="Run User">{worker.run_user || "-"}</Descriptions.Item>
          <Descriptions.Item label="Connectivity">{worker.connectivity_status ?? worker.status}</Descriptions.Item>
          <Descriptions.Item label="Dispatch State">{worker.dispatch_status ?? worker.state ?? "-"}</Descriptions.Item>
          <Descriptions.Item label="Heartbeat Age">
            {typeof worker.heartbeat_age_seconds === "number" ? `${worker.heartbeat_age_seconds.toFixed(1)}s` : "-"}
          </Descriptions.Item>
          <Descriptions.Item label="Running Users">
            {worker.running_users?.length ? worker.running_users.join(", ") : "-"}
          </Descriptions.Item>
          <Descriptions.Item label="Last heartbeat">
            {worker.last_heartbeat ? new Date(worker.last_heartbeat * 1000).toLocaleString() : "-"}
          </Descriptions.Item>
          <Descriptions.Item label="Metrics updated">
            {worker.metrics_updated_at ? new Date(worker.metrics_updated_at * 1000).toLocaleString() : "-"}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card
        title="Affinity tags"
        extra={
          <Space>
            <Button size="small" onClick={() => setStateMutation.mutate("online")} loading={setStateMutation.isPending}>
              Online
            </Button>
            <Button size="small" onClick={() => setStateMutation.mutate("draining")} loading={setStateMutation.isPending}>
              Drain
            </Button>
            <Button
              size="small"
              onClick={() => setStateMutation.mutate("offline")}
              loading={setStateMutation.isPending}
            >
              Offline
            </Button>
          </Space>
        }
      >
        <Space wrap>
          {(worker.tags ?? []).map((t) => (
            <Tag key={t}>{t}</Tag>
          ))}
          {!(worker.tags ?? []).length && <Typography.Text type="secondary">No tags advertised.</Typography.Text>}
        </Space>
        <Typography.Paragraph style={{ marginTop: 12, marginBottom: 0 }}>
          Allowed users: {worker.allowed_users?.length ? worker.allowed_users.join(", ") : "any"}
        </Typography.Paragraph>
        <Typography.Paragraph style={{ marginTop: 8, marginBottom: 0 }}>
          Shells: {(worker.shells ?? []).length ? (worker.shells ?? []).map((s) => <Tag key={s} color="blue">{s}</Tag>) : <Typography.Text type="secondary">none detected</Typography.Text>}
        </Typography.Paragraph>
        <Typography.Paragraph style={{ marginTop: 8, marginBottom: 0 }}>
          Capabilities: {(worker.capabilities ?? []).length ? (worker.capabilities ?? []).map((c) => <Tag key={c} color="cyan">{c}</Tag>) : <Typography.Text type="secondary">none detected</Typography.Text>}
        </Typography.Paragraph>
      </Card>

      <Card title="Running jobs">
        <List
          dataSource={worker.running_jobs ?? []}
          locale={{ emptyText: "No running jobs on this worker." }}
          renderItem={(jobId: string) => <List.Item>{jobId}</List.Item>}
        />
      </Card>

      <Card title="Operational Timeline">
        <List
          loading={operationsQuery.isLoading}
          dataSource={operationsQuery.data?.events ?? []}
          locale={{ emptyText: "No operational events yet." }}
          renderItem={(event: WorkerOperation) => (
            <List.Item onClick={() => event.details?.run_id && setInspectedRunId(String(event.details.run_id))} style={{ cursor: event.details?.run_id ? "pointer" : "default" }}>
              <Space direction="vertical" style={{ width: "100%" }} size={2}>
                <Space wrap>
                  <Tag color={opColor(event.type)}>{event.type}</Tag>
                  <Typography.Text strong>{event.message}</Typography.Text>
                  <Typography.Text type="secondary">{new Date(event.ts * 1000).toLocaleString()}</Typography.Text>
                </Space>
                {event.details && Object.keys(event.details).length > 0 && (
                  <Typography.Text type="secondary">
                    {Object.entries(event.details)
                      .map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`)
                      .join(" · ")}
                  </Typography.Text>
                )}
              </Space>
            </List.Item>
          )}
        />
      </Card>
      <RunInspector runId={inspectedRunId} open={Boolean(inspectedRunId)} onClose={() => setInspectedRunId(undefined)} />
    </Space>
  );
}
