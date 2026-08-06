import { apiClient } from "./client";

export interface HealthStatus {
  status: string;
  workers: number;
  pending_jobs: number;
  demo_mode: boolean;
}

export const fetchHealth = () => apiClient.get<HealthStatus>("/health");
