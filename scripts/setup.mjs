import { spawnSync } from "node:child_process";
import { mkdirSync } from "node:fs";
function execute(cmd, args) {
  const r = spawnSync(cmd, args, { stdio: "inherit" });
  if (r.error || r.status !== 0) process.exit(r.status || 1);
}
execute("uv", ["venv", "--allow-existing", "--python", "3.12", ".venv"]);
execute("uv", [
  "pip",
  "install",
  "--python",
  ".venv/bin/python",
  "-r",
  "requirements.txt",
]);
if (process.platform === "darwin") {
  mkdirSync(".trupic/bin", { recursive: true, mode: 0o700 });
  const build = spawnSync(
    "swiftc",
    ["-O", "scripts/cutout.swift", "-o", ".trupic/bin/cutout"],
    { stdio: "inherit" },
  );
  if (build.status !== 0)
    console.warn("系统主体分割工具未就绪，仍可使用原图与曝光校正。");
}
