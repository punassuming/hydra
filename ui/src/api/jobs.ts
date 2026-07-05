import { apiClient } from "./client";
import {
  JobDefinition,
  JobRun,
  WorkerInfo,
  ScheduleConfig,
  CompletionCriteria,
  JobOverview,
  JobGridData,
  JobGanttData,
  JobGraphData,
  JobStatistics,
  WorkerMetricsData,
  WorkerTimelineData,
  WorkerOperationsData,
  SourceConfig,
  QueueOverview,
  QueuePressure,
} from "../types";

export interface JobPayload {
  name: string;
  user: string;
  priority: number;
  affinity: JobDefinition["affinity"];
  executor: JobDefinition["executor"];
  retries: number;
  timeout: number;
  bypass_concurrency?: boolean;
  source?: SourceConfig | null;
  schedule: ScheduleConfig;
  completion: CompletionCriteria;
  tags?: string[];
  depends_on?: string[];
  retry_count?: number | null;
  max_retries?: number;
  retry_delay_seconds?: number;
  on_failure_webhooks?: string[];
  on_failure_email_to?: string[];
  on_failure_email_credential_ref?: string;
  sla_max_duration_seconds?: number | null;
}

export interface ValidationResult {
  valid: boolean;
  errors: string[];
  next_run_at?: string | null;
}

export const fetchJobs = (params?: { search?: string; tags?: string }) => {
  const queryParams = new URLSearchParams();
  if (params?.search) queryParams.append("search", params.search);
  if (params?.tags) queryParams.append("tags", params.tags);
  const queryString = queryParams.toString();
  return apiClient.get<JobDefinition[]>(`/jobs/${queryString ? `?${queryString}` : ""}`);
};
export const fetchJob = (jobId: string) => apiClient.get<JobDefinition>(`/jobs/${jobId}`);
export const fetchWorkers = () => apiClient.get<WorkerInfo[]>("/workers/");
export const fetchWorkerMetrics = (workerId: string, minutes = 30) =>
  apiClient.get<WorkerMetricsData>(`/workers/${workerId}/metrics?minutes=${minutes}`);
export const fetchWorkerTimeline = (workerId: string, minutes = 180) =>
  apiClient.get<WorkerTimelineData>(`/workers/${workerId}/timeline?minutes=${minutes}`);
export const fetchWorkerOperations = (workerId: string, limit = 250) =>
  apiClient.get<WorkerOperationsData>(`/workers/${workerId}/operations?limit=${limit}`);
export const detachWorker = (workerId: string, force = false) =>
  apiClient.post<{ ok: boolean; domain: string; worker_id: string; detached: boolean; requeued_jobs: number }>(
    `/workers/${workerId}/detach${force ? "?force=true" : ""}`,
    {},
  );
export const fetchJobRuns = (jobId: string) => apiClient.get<JobRun[]>(`/jobs/${jobId}/runs`);
export const fetchJobOverview = () => apiClient.get<JobOverview[]>("/overview/jobs");
export const fetchQueueOverview = () => apiClient.get<QueueOverview>("/overview/queue");
export const fetchQueuePressure = () => apiClient.get<QueuePressure>("/overview/pressure");
export const fetchJobStatistics = () => apiClient.get<JobStatistics>("/overview/statistics");
export const fetchHistory = () => apiClient.get<JobRun[]>("/history/");
export const fetchJobGrid = (jobId: string) => apiClient.get<JobGridData>(`/jobs/${jobId}/grid`);
export const fetchJobGantt = (jobId: string) => apiClient.get<JobGanttData>(`/jobs/${jobId}/gantt`);
export const fetchJobGraph = (jobId: string) => apiClient.get<JobGraphData>(`/jobs/${jobId}/graph`);
export const createJob = (payload: JobPayload) => apiClient.post<JobDefinition>("/jobs/", payload);
export const updateJob = (jobId: string, payload: Partial<JobPayload>) =>
  apiClient.put<JobDefinition>(`/jobs/${jobId}`, payload);
export const deleteJob = (jobId: string) =>
  apiClient.delete<{ job_id: string; deleted: boolean }>(`/jobs/${jobId}`);
export const setJobEnabled = (job: JobDefinition, enabled: boolean) =>
  apiClient.put<JobDefinition>(`/jobs/${job._id}`, {
    schedule: { ...job.schedule, enabled },
  } as Partial<JobPayload>);
export const validateJob = (payload: JobPayload) => apiClient.post<ValidationResult>("/jobs/validate", payload);
export const validateJobById = (jobId: string) => apiClient.post<ValidationResult>(`/jobs/${jobId}/validate`, {});
export const runJobNow = (jobId: string, params?: Record<string, string>) =>
  apiClient.post<{ job_id: string; queued: boolean }>(`/jobs/${jobId}/run`, { params: params ?? {} });
export const killRun = (runId: string) => apiClient.post<{ run_id: string; signal: string }>(`/runs/${runId}/kill`, {});
export const runAdhocJob = (payload: JobPayload) => apiClient.post<JobDefinition>("/jobs/adhoc", payload);
export const backfillJob = (jobId: string, startDate: string, endDate: string) =>
  apiClient.post<{ job_id: string; queued_count: number; start_date: string; end_date: string }>(
    `/jobs/${jobId}/backfill`,
    { start_date: startDate, end_date: endDate },
  );

export const generateJob = (prompt: string, provider: "gemini" | "openai" = "gemini", model?: string) =>
  apiClient.post<JobPayload>("/ai/generate_job", { prompt, provider, model });

export const fetchTemplates = () => apiClient.get<JobPayload[]>("/jobs/templates");

export const analyzeRun = (payload: {
  run_id: string;
  stdout: string;
  stderr: string;
  exit_code: number;
  provider?: "gemini" | "openai";
  model?: string;
  analysis_type?: "failure" | "summary" | "errors" | "retry" | "custom";
  question?: string;
}) =>
  apiClient.post<{ analysis: string }>("/ai/analyze_run", { provider: "gemini", ...payload });
