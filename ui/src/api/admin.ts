import { apiClient } from "./client";

export interface DomainInfo {
  domain: string;
  display_name?: string;
  description?: string;
  token?: string;
  jobs_count?: number;
  runs_count?: number;
  workers_count?: number;
}

export const fetchDomains = () => apiClient.get<{ domains: DomainInfo[] }>("/admin/domains");
export const createDomain = (payload: DomainInfo) => apiClient.post<DomainInfo>("/admin/domains", payload);
export const updateDomain = (domain: string, payload: Partial<DomainInfo>) =>
  apiClient.put(`/admin/domains/${domain}`, payload);
export const rotateDomainToken = (domain: string) => apiClient.post<{ ok: boolean; domain: string; token: string }>(`/admin/domains/${domain}/token`, {});
