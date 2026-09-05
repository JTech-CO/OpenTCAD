import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import {
  PowerLossLedgerError,
  parseAndValidatePhysicalPowerLossLedger,
} from "../validation/power-loss/ledger.mjs";

const [path, ...extra] = process.argv.slice(2);
if (!path || extra.length > 0) {
  console.error("usage: node tools/check-m3-power-loss.mjs <ledger.json>");
  process.exitCode = 2;
} else {
  try {
    const bytes = await readFile(resolve(path));
    if (bytes.length < 1 || bytes.length > 16 * 1024 * 1024) {
      throw new PowerLossLedgerError("power-loss-ledger-invalid");
    }
    const source = bytes.toString("utf8");
    if (Buffer.from(source, "utf8").compare(bytes) !== 0) {
      throw new PowerLossLedgerError("power-loss-ledger-invalid");
    }
    const result = parseAndValidatePhysicalPowerLossLedger(source);
    console.log(JSON.stringify(result, null, 2));
  } catch (error) {
    const code =
      error instanceof PowerLossLedgerError
        ? error.code
        : "power-loss-ledger-invalid";
    console.error(JSON.stringify({ eligibleForGateReview: false, code }));
    process.exitCode = 1;
  }
}
