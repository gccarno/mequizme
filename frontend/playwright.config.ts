import { defineConfig } from "@playwright/test";

const port = Number(process.env.E2E_PORT ?? 8765);

export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  use: { baseURL: `http://127.0.0.1:${port}`, viewport: { width: 1280, height: 860 } },
  webServer: {
    // Serves the built frontend (run `npm run build` first) from a throwaway database, a draft-free
    // copy of the content and the offline fake tutor. See backend/tests/e2e_server.py.
    command: `uv run --project ../backend python ../backend/tests/e2e_server.py ${port}`,
    url: `http://127.0.0.1:${port}/api/health`,
    reuseExistingServer: false,
  },
});
