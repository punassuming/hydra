import { apiClient } from "./client";

export interface DomainInfo {
  domain: string;
  display_name?: string;
  description?: string;
  token?: string;
}

export const fetchDomains = () => apiClient.get<{ domains: DomainInfo[] }>("/admin/domains");
export const createDomain = (payload: DomainInfo) => apiClient.post("/admin/domains", payload);
export const updateDomain = (domain: string, payload: Partial<DomainInfo>) =>
  apiClient.put(`/admin/domains/${domain}`, payload);
