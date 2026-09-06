import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    globals: true,
    css: false,
    // Provider-heavy component trees (antd + react-query + router) take
    // noticeably longer to mount under the current vitest/vite/jsdom stack
    // than the previous one did — comfortably under 10s, but that's already
    // tight against the 5s default, and different tests trip it on
    // different runs/machines (seen in CI on AppNavigation.test.tsx, locally
    // on JobList.test.tsx). Raise the default rather than bumping timeouts
    // test-by-test as each one happens to tip over.
    testTimeout: 20000,
  },
});
