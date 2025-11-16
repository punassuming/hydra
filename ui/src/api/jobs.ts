import { apiClient } from "./client";
import { JobDefinition, JobRun, WorkerInfo } from "../types";

export interface JobPayload {
  name: string;
  user: string;
  affinity: JobDefinition["affinity"];
  executor: JobDefinition["executor"];
  retries: number;
  timeout: number;
  schedule?: string | null;
}

export const fetchJobs = () => apiClient.get<JobDefinition[]>("/jobs/");
export const fetchWorkers = () => apiClient.get<WorkerInfo[]>("/workers/");
export const fetchJobRuns = (jobId: string) => apiClient.get<JobRun[]>(`/jobs/${jobId}/runs`);
export const createJob = (payload: JobPayload) => apiClient.post<JobDefinition>("/jobs/", payload);
export const updateJob = (jobId: string, payload: Partial<JobPayload>) =>
  apiClient.put<JobDefinition>(`/jobs/${jobId}`, payload);
export const validateJob = (payload: JobPayload) => apiClient.post<{ valid: boolean; errors: string[] }>("/jobs/validate", payload);
export const validateJobById = (jobId: string) =>
  apiClient.post<{ valid: boolean; errors: string[] }>(`/jobs/${jobId}/validate`, {});
