// Default runtime config for local dev / `vite build` without Docker.
// In the container, ui/docker-entrypoint.sh overwrites this file from
// HYDRA_API_BASE_URL at startup so the same image can point at different
// scheduler endpoints without a rebuild.
window.__HYDRA_API_BASE__ = "";
