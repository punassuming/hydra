import { apiClient } from "./client";

export interface InvestigationCatalogItem {
  key: string;
  label: string;
  description: string;
}

export interface InvestigationResultRow {
  job_id: string;
  job_name: string;
  domain: string;
  metric_label: string;
  metric_value: number;
  last_run_id: string | null;
  last_run_at: string | null;
}

export interface InvestigationResult {
  key: string;
  label: string;
  results: InvestigationResultRow[];
}

export const fetchInvestigationCatalog = () => apiClient.get<InvestigationCatalogItem[]>("/investigations/");
export const runInvestigation = (key: string) => apiClient.get<InvestigationResult>(`/investigations/${key}`);
