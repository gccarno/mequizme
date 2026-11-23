import { defineConfig } from "@playwright/test";
import { tmpdir } from "node:os";
import { join } from "node:path";

const port = Number(process.env.E2E_PORT ?? 8765);

export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  use: { baseURL: `http://127.0.0.1:${port}`, viewport: { width: 1280, height: 860 } },
  webServer: {
    // Serves the built frontend (run `npm run build` first) from a throwaway database.
    command: `uv run --project ../backend mequizme --port ${port}`,
    url: `http://127.0.0.1:${port}/api/health`,
    reuseExistingServer: true,
    env: { MEQUIZME_DB: join(tmpdir(), `mequizme-e2e-${Date.now()}.db`) },
  },
});
