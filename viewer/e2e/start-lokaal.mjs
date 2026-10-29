// Web server for the browser test: a fresh project folder with two test models, served by `openbim-kern lokaal`.
//   OPENBIM_PYTHON  Python with openbim_kern installed (default: kern/.venv, else `python`)
import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdtempSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const kern = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "kern");
const venv = path.join(kern, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const python = process.env.OPENBIM_PYTHON ?? (existsSync(venv) ? venv : "python");
const port = process.env.E2E_LOKAAL_POORT ?? "8749";
const kernPort = process.env.E2E_KERN_POORT ?? "8739";

const work = mkdtempSync(path.join(os.tmpdir(), "openbim-e2e-"));
const folder = path.join(work, "Proefproject");
const made = spawnSync(python, ["-m", "tests.models", folder], { cwd: kern, stdio: "inherit" });
if (made.status !== 0) process.exit(made.status ?? 1);

const server = spawn(
  python,
  ["-m", "openbim_kern.cli", "lokaal", folder, "--poort", port, "--kern-poort", kernPort],
  { cwd: kern, stdio: "inherit", env: { ...process.env, OPENBIM_KERN_DATA: path.join(work, "data") } },
);
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => server.kill(signal));
server.on("exit", (code) => process.exit(code ?? 0));
