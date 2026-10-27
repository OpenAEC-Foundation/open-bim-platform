/// <reference types="vitest/config" />
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

const FRAGMENTS_MODELS = /[\\/]@thatopen[\\/]fragments[\\/]dist[\\/]FragmentsModels[\\/]index\.mjs$/;
const FRAGMENTS_CDN_WORKER = "const url = `https://unpkg.com/@thatopen/fragments@${FRAGMENTS_VERSION}/dist/Worker/worker.mjs`;";

/**
 * FragmentsModels.getWorker() can fetch the fragments worker from a CDN. The viewer always passes the worker from its
 * own bundle, so that path is removed from the build; when the library changes, the build fails instead of quietly
 * keeping a CDN address (npm run check:geen-cdn checks the whole bundle as well).
 */
function bundledFragmentsWorkerOnly(): Plugin {
  return {
    name: "openbim:bundled-fragments-worker-only",
    enforce: "pre",
    apply: "build",
    transform(code, id) {
      if (!FRAGMENTS_MODELS.test(id.split("?")[0])) return null;
      if (!code.includes(FRAGMENTS_CDN_WORKER)) {
        this.error("@thatopen/fragments changed: FragmentsModels.getWorker no longer has the expected CDN fallback.");
      }
      return code.replace(
        FRAGMENTS_CDN_WORKER,
        'throw new Error("The Open BIM viewer loads the fragments worker from its own bundle, never from a CDN.");',
      );
    },
  };
}

export default defineConfig({
  plugins: [react(), bundledFragmentsWorkerOnly()],
  resolve: {
    alias: {
      // The shell's title bar can drive desktop window controls; in the browser there are none.
      "@tauri-apps/api/window": fileURLToPath(new URL("./src/host/noWindowControls.ts", import.meta.url)),
    },
  },
  server: { host: "127.0.0.1", port: 5173, strictPort: true },
  build: { target: "es2022", chunkSizeWarningLimit: 4096 },
  test: { include: ["src/**/*.test.ts"], environment: "node" },
});
