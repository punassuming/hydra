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

export interface JobDefinition {
  _id: string;
  name: string;
  user: string;
  affinity: Affinity;
  executor: Executor;
  retries: number;
  timeout: number;
  schedule?: string | null;
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
