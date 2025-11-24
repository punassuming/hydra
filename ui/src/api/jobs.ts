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
  QueueOverview,
} from "../types";

export interface JobPayload {
  name: string;
  user: string;
  priority: number;
  affinity: JobDefinition["affinity"];
  executor: JobDefinition["executor"];
  retries: number;
  timeout: number;
  schedule: ScheduleConfig;
  completion: CompletionCriteria;
}

export interface ValidationResult {
  valid: boolean;
  errors: string[];
  next_run_at?: string | null;
}

export const fetchJobs = () => apiClient.get<JobDefinition[]>("/jobs/");
export const fetchJob = (jobId: string) => apiClient.get<JobDefinition>(`/jobs/${jobId}`);
export const fetchWorkers = () => apiClient.get<WorkerInfo[]>("/workers/");
export const fetchJobRuns = (jobId: string) => apiClient.get<JobRun[]>(`/jobs/${jobId}/runs`);
export const fetchJobOverview = () => apiClient.get<JobOverview[]>("/overview/jobs");
export const fetchQueueOverview = () => apiClient.get<QueueOverview>("/queue/overview");
export const fetchHistory = () => apiClient.get<JobRun[]>("/history/");
export const fetchJobGrid = (jobId: string) => apiClient.get<JobGridData>(`/jobs/${jobId}/grid`);
export const fetchJobGantt = (jobId: string) => apiClient.get<JobGanttData>(`/jobs/${jobId}/gantt`);
export const fetchJobGraph = (jobId: string) => apiClient.get<JobGraphData>(`/jobs/${jobId}/graph`);
export const createJob = (payload: JobPayload) => apiClient.post<JobDefinition>("/jobs/", payload);
export const updateJob = (jobId: string, payload: Partial<JobPayload>) =>
  apiClient.put<JobDefinition>(`/jobs/${jobId}`, payload);
export const validateJob = (payload: JobPayload) => apiClient.post<ValidationResult>("/jobs/validate", payload);
export const validateJobById = (jobId: string) => apiClient.post<ValidationResult>(`/jobs/${jobId}/validate`, {});
export const runJobNow = (jobId: string) => apiClient.post<{ job_id: string; queued: boolean }>(`/jobs/${jobId}/run`, {});
export const runAdhocJob = (payload: JobPayload) => apiClient.post<JobDefinition>("/jobs/adhoc", payload);
