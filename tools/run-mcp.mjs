import {spawn} from "node:child_process";
import {existsSync} from "node:fs";
import {fileURLToPath} from "node:url";
import path from "node:path";
const root = fileURLToPath(new URL("../", import.meta.url));
const python = process.env.OPENTCAD_LAB_PYTHON || path.join(root,".venv-mvp",process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
if (!existsSync(python)) {
  console.error("Install the local Python environment before starting OpenTCAD MCP.");
  process.exit(1);
}
const child = spawn(python,["-m","backend.app.experimental.mcp_server",...process.argv.slice(2)],
  {cwd:root,env:{...process.env,PYTHONUTF8:"1"},shell:false,windowsHide:true,stdio:"inherit"});
child.on("error",()=>{console.error("MCP process unavailable.");process.exitCode=1;});
child.on("exit",code=>{process.exitCode=code ?? 1;});
for (const signal of ["SIGINT","SIGTERM"]) process.on(signal,()=>child.kill(signal));
