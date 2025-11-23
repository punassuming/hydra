export interface Affinity {
  os: string[];
  tags: string[];
  allowed_users: string[];
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
    }
  | {
      type: "shell";
      script: string;
      shell?: string;
      args?: string[];
      env?: Record<string, string>;
      workdir?: string | null;
    }
  | {
      type: "batch";
      script: string;
      shell?: string;
      args?: string[];
      env?: Record<string, string>;
      workdir?: string | null;
    }
  | {
      type: "external";
      command: string;
      args?: string[];
      env?: Record<string, string>;
      workdir?: string | null;
    };

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
  enabled: boolean;
}

export interface CompletionCriteria {
  exit_codes: number[];
  stdout_contains: string[];
  stdout_not_contains: string[];
  stderr_contains: string[];
  stderr_not_contains: string[];
}

export interface JobDefinition {
  _id: string;
  name: string;
  user: string;
  affinity: Affinity;
  executor: Executor;
  retries: number;
  timeout: number;
  schedule: ScheduleConfig;
  completion: CompletionCriteria;
  created_at: string;
  updated_at: string;
}

export interface JobRun {
  _id: string;
  job_id: string;
  user: string;
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
}

export interface JobOverview {
  job_id: string;
  name: string;
  schedule_mode: string;
  total_runs: number;
  success_runs: number;
  failed_runs: number;
  last_run?: JobRun;
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
  os: string;
  tags: string[];
  allowed_users: string[];
  max_concurrency: number;
  current_running: number;
  last_heartbeat?: number;
  status: string;
}

export interface SchedulerEvent {
  type: string;
  payload: Record<string, unknown>;
  ts: number;
}
