import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";

// Release policy: no high/critical advisories; advisory-service failures also fail.
// Keep the raw report in CI output so development/build exposure can be triaged.
let report;
try {
  const fixture = process.argv.indexOf("--audit-file");
  if (fixture !== -1) report = JSON.parse(readFileSync(process.argv[fixture + 1], "utf8"));
  else {
    const result = spawnSync("npm", ["audit", "--json"], { encoding: "utf8", timeout: 120_000 });
    if (result.error) throw result.error;
    report = JSON.parse(result.stdout);
  }
  if (report.error || !report.metadata?.vulnerabilities || !report.vulnerabilities) {
    throw new Error("The advisory service did not return a complete vulnerability report.");
  }
  const counts = report.metadata.vulnerabilities;
  if (![counts.high, counts.critical].every((count) => Number.isInteger(count) && count >= 0)) {
    throw new Error("The advisory report is missing severity counts.");
  }
  const blocked = Object.values(report.vulnerabilities)
    .filter((item) => item.severity === "high" || item.severity === "critical");
  if (blocked.length || counts.high || counts.critical) {
    console.error(`Blocked advisories: ${counts.high} high, ${counts.critical} critical.`);
    for (const item of blocked) console.error(`${item.severity}: ${item.name}\n${JSON.stringify(item.via)}`);
    process.exitCode = 1;
  } else console.log("Dependency policy passed: no high or critical npm advisories.");
} catch (error) {
  console.error(`Dependency audit failed: ${error.message}`);
  process.exitCode = 1;
}
