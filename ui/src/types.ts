export interface Affinity {
  os: string[];
  tags: string[];
  allowed_users: string[];
  hostnames?: string[];
  subnets?: string[];
  deployment_types?: string[];
  executor_types?: string[];
}

export type Executor =
  | {
      type: "python";
      code: string;
      interpreter?: string;
      environment?: PythonEnvironment;
      args?: string[];
      env?: Record<string, string>;
      workdir?: string | null;
      impersonate_user?: string | null;
      kerberos?: KerberosConfig | null;
    }
  | {
      type: "shell";
      script: string;
      shell?: string;
      args?: string[];
      env?: Record<string, string>;
      workdir?: string | null;
      impersonate_user?: string | null;
      kerberos?: KerberosConfig | null;
    }
  | {
      type: "batch";
      script: string;
      shell?: string;
      args?: string[];
      env?: Record<string, string>;
      workdir?: string | null;
      impersonate_user?: string | null;
      kerberos?: KerberosConfig | null;
    }
  | {
      type: "powershell";
      script: string;
      shell?: string;
      args?: string[];
      env?: Record<string, string>;
      workdir?: string | null;
      impersonate_user?: string | null;
      kerberos?: KerberosConfig | null;
    }
  | {
      type: "sql";
      dialect?: string;
      connection_uri?: string;
      credential_ref?: string;
      query: string;
      database?: string;
      args?: string[];
      env?: Record<string, string>;
      workdir?: string | null;
      impersonate_user?: string | null;
      kerberos?: KerberosConfig | null;
    }
  | {
      type: "external";
      command: string;
      args?: string[];
      env?: Record<string, string>;
      workdir?: string | null;
      impersonate_user?: string | null;
      kerberos?: KerberosConfig | null;
    }
  | {
      type: "http";
      url: string;
      method?: string;
      body?: string;
      headers?: Record<string, string>;
      expected_status?: number;
      timeout_seconds?: number;
      env?: Record<string, string>;
    }
  | {
      type: "sensor";
      condition: string;
      poll_interval?: number;
      max_wait?: number;
      env?: Record<string, string>;
      workdir?: string | null;
    };

export interface KerberosConfig {
  principal: string;
  keytab: string;
  ccache?: string | null;
}

export interface PythonEnvironment {
  type: "system" | "venv" | "uv";
  python_version?: string | null;
  venv_path?: string | null;
  requirements?: string[];
  requirements_file?: string | null;
}

export interface ScheduleConfig {
  mode: "immediate" | "cron" | "interval";
  cron?: string | null;
  interval_seconds?: number | null;
  start_at?: string | null;
  end_at?: string | null;
  next_run_at?: string | null;
  timezone?: string;
  enabled: boolean;
}

export interface CompletionCriteria {
  exit_codes: number[];
  stdout_contains: string[];
  stdout_not_contains: string[];
  stderr_contains: string[];
  stderr_not_contains: string[];
}

export interface SourceConfig {
  protocol?: "git" | "copy" | "rsync";
  url: string;
  ref?: string;
  path?: string | null;
  sparse?: boolean;
  credential_ref?: string | null;
}

export interface JobDefinition {
  _id: string;
  name: string;
  user: string;
  domain?: string;
  bypass_concurrency?: boolean;
  source?: SourceConfig | null;
  priority: number;
  affinity: Affinity;
  executor: Executor;
  retries: number;
  timeout: number;
  schedule: ScheduleConfig;
  completion: CompletionCriteria;
  tags: string[];
  depends_on?: string[];
  max_retries?: number;
  retry_delay_seconds?: number;
  on_failure_webhooks?: string[];
  on_failure_email_to?: string[];
  on_failure_email_credential_ref?: string;
  sla_max_duration_seconds?: number | null;
  created_at: string;
  updated_at: string;
}

export interface JobRun {
  _id: string;
  job_id: string;
  user: string;
  domain?: string;
  worker_id?: string;
  start_ts?: string;
  scheduled_ts?: string;
  end_ts?: string;
  status: string;
  returncode?: number;
  stdout: string;
  stderr: string;
  slot?: number;
  attempt?: number;
  retries_remaining?: number;
  schedule_tick?: string;
  executor_type?: string;
  queue_latency_ms?: number;
  completion_reason?: string;
  stdout_tail?: string;
  stderr_tail?: string;
  duration?: number | null;
  bypass_concurrency?: boolean;
}

export interface HistoryPage {
  items: JobRun[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface JobOverview {
  job_id: string;
  name: string;
  schedule_mode: string;
  tags: string[];
  total_runs: number;
  success_runs: number;
  failed_runs: number;
  queued_runs?: number;
  last_run?: JobRun;
  recent_runs?: JobRun[];
  avg_duration_seconds?: number | null;
  last_failure_reason?: string | null;
}

export interface JobStatistics {
  total_jobs: number;
  schedule_breakdown: {
    cron: number;
    interval: number;
    immediate: number;
  };
  enabled_jobs: number;
  disabled_jobs: number;
  total_runs: number;
  success_runs: number;
  failed_runs: number;
  running_runs: number;
  success_rate: number;
  available_tags: string[];
}

export interface QueueJobItem {
  job_id: string;
  name: string;
  user?: string;
  domain?: string;
  priority?: number;
  schedule_mode?: string;
  next_run_at?: string | null;
  queue_score?: number;
  enqueued_ts?: string | null;
  reason?: string;
  no_worker_count?: number;
}

export interface QueueOverview {
  pending: QueueJobItem[];
  upcoming: QueueJobItem[];
  pending_total?: Record<string, number>;
}

export interface DomainPressure {
  domain: string;
  pending_total: number;
  stalled_jobs: string[];
  stalled_count: number;
  max_no_worker_count: number;
  starvation_threshold: number;
  worker_queue_depths: Record<string, number>;
  total_worker_queue_depth: number;
  online_workers: number;
  total_running: number;
  total_capacity: number;
}

export interface QueuePressure {
  domains: DomainPressure[];
}

export interface JobGridTaskInstance {
  run_id: string;
  status?: string;
  start_ts?: string | null;
  end_ts?: string | null;
  duration?: number | null;
}

export interface JobGridTask {
  task_id: string;
  label: string;
  instances: JobGridTaskInstance[];
}

export interface JobGridData {
  runs: JobGridTaskInstance[];
  tasks: JobGridTask[];
}

export interface JobGanttEntry {
  run_id: string;
  status?: string;
  start_ts?: string | null;
  end_ts?: string | null;
  duration?: number | null;
}

export interface JobGanttData {
  entries: JobGanttEntry[];
}

export interface JobGraphData {
  nodes: { id: string; label: string; status?: string }[];
  edges: { source: string; target: string }[];
}

export interface WorkerInfo {
  worker_id: string;
  domain?: string;
  os: string;
  tags: string[];
  allowed_users: string[];
  max_concurrency: number;
  current_running: number;
  last_heartbeat?: number;
  status: string;
  state?: string;
  hostname?: string;
  ip?: string;
  subnet?: string;
  deployment_type?: string;
  run_user?: string;
  cpu_count?: number;
  python_version?: string;
  cwd?: string;
  shells?: string[];
  capabilities?: string[];
  process_count?: number;
  memory_rss_mb?: number;
  load_1m?: number;
  load_5m?: number;
  process_count_max_30m?: number;
  memory_rss_mb_max_30m?: number;
  load_1m_max_30m?: number;
  metrics_updated_at?: number;
  running_jobs?: string[];
  running_users?: string[];
  connectivity_status?: "online" | "offline";
  dispatch_status?: "online" | "draining" | "offline";
  heartbeat_age_seconds?: number;
}

export interface WorkerMetricPoint {
  ts: number;
  memory_rss_mb?: number | null;
  process_count?: number | null;
  load_1m?: number | null;
  load_5m?: number | null;
}

export interface WorkerMetricsData {
  worker_id: string;
  domain: string;
  window_minutes: number;
  points: WorkerMetricPoint[];
}

export interface WorkerTimelineEntry {
  run_id: string;
  job_id: string;
  job_name?: string;
  status: string;
  start_ts: number;
  end_ts: number;
  slot: number;
  bypass_concurrency?: boolean;
}

export interface WorkerTimelineData {
  worker_id: string;
  domain: string;
  window_minutes: number;
  window_start_ts: number;
  window_end_ts: number;
  max_concurrency: number;
  entries: WorkerTimelineEntry[];
}

export interface WorkerOperation {
  ts: number;
  type: string;
  message: string;
  details?: Record<string, unknown>;
}

export interface WorkerOperationsData {
  worker_id: string;
  domain: string;
  events: WorkerOperation[];
}

export interface SchedulerEvent {
  type: string;
  payload: Record<string, unknown>;
  ts: number;
}
