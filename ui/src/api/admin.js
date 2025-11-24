import { apiClient } from "./client";
export const fetchDomains = () => apiClient.get("/admin/domains");
export const createDomain = (payload) => apiClient.post("/admin/domains", payload);
export const updateDomain = (domain, payload) => apiClient.put(`/admin/domains/${domain}`, payload);
