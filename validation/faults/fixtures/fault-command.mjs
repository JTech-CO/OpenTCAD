const [mode, value = ""] = process.argv.slice(2);

switch (mode) {
  case "echo":
    process.stdout.write(value);
    break;
  case "stderr":
    process.stderr.write(value);
    break;
  case "hang":
    setInterval(() => {}, 1_000);
    break;
  case "output": {
    const bytes = Number.parseInt(value, 10);
    if (!Number.isInteger(bytes) || bytes < 0) throw new Error("output bytes must be non-negative.");
    process.stdout.write(Buffer.alloc(bytes, 120));
    break;
  }
  case "mixed-output": {
    const bytes = Number.parseInt(value, 10);
    if (!Number.isInteger(bytes) || bytes < 0) throw new Error("output bytes must be non-negative.");
    const stdoutBytes = Math.floor(bytes / 2);
    process.stdout.write(Buffer.alloc(stdoutBytes, 120));
    process.stderr.write(Buffer.alloc(bytes - stdoutBytes, 121));
    break;
  }
  case "exit":
    process.exitCode = Number.parseInt(value, 10);
    break;
  default:
    throw new Error(`Unknown fault fixture mode: ${mode}`);
}
