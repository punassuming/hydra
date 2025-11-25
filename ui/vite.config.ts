import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
  },
  build: {
    outDir: "dist",
  },
  preview: {
    port: 4173,
  },
  resolve: {
    alias: [],
  },
  base: "/",
  define: {},
  // For SPA routing in Docker/nginx, ensure index fallback is used
  appType: "spa",
});
