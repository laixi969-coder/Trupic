import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
if (!existsSync(".venv/bin/python")) {
  console.error("请先运行 npm run setup 安装服务端依赖。");
  process.exit(1);
}
const api = spawn(".venv/bin/python", ["-m", "server.app"], {
  stdio: "inherit",
  env: { ...process.env, PORT: "7342" },
});
const vite = spawn(
  "node",
  ["node_modules/vite/bin/vite.js", ...process.argv.slice(2)],
  { stdio: "inherit" },
);
let stopped = false;
function stop(code = 0) {
  if (stopped) return;
  stopped = true;
  api.kill();
  vite.kill();
  process.exit(code);
}
api.on("exit", (code) => stop(code ?? 1));
vite.on("exit", (code) => stop(code ?? 0));
process.on("SIGINT", () => stop());
process.on("SIGTERM", () => stop());
