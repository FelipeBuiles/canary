import { spawnSync } from "node:child_process";

const NON_APPLICABLE_ADVISORIES = new Set(["GHSA-qwww-vcr4-c8h2"]);
const result = spawnSync(
  "npm",
  ["audit", "--omit=dev", "--audit-level=high", "--json"],
  { encoding: "utf8" },
);

if (result.error) {
  console.error(`npm audit could not start: ${result.error.message}`);
  process.exit(1);
}

let report;
try {
  report = JSON.parse(result.stdout);
} catch {
  console.error("npm audit did not return valid JSON.");
  if (result.stderr) console.error(result.stderr.trim());
  process.exit(1);
}

const actionable = [];
const ignored = [];
for (const [packageName, vulnerability] of Object.entries(
  report.vulnerabilities ?? {},
)) {
  for (const advisory of vulnerability.via ?? []) {
    if (!advisory || typeof advisory !== "object") continue;
    if (!new Set(["high", "critical"]).has(advisory.severity)) continue;

    const advisoryId = advisory.url?.match(/advisories\/([^/]+)$/)?.[1];
    const finding = {
      packageName,
      advisoryId: advisoryId ?? String(advisory.source ?? "unknown"),
      title: advisory.title ?? "Unknown advisory",
      url: advisory.url ?? "",
    };
    if (NON_APPLICABLE_ADVISORIES.has(advisoryId)) {
      ignored.push(finding);
    } else {
      actionable.push(finding);
    }
  }
}

if (actionable.length > 0) {
  console.error("Production dependency audit found actionable vulnerabilities:");
  for (const finding of actionable) {
    console.error(`- ${finding.packageName}: ${finding.title} (${finding.url})`);
  }
  process.exit(1);
}

if (ignored.length > 0) {
  console.log(
    `Production dependency audit passed; ignored ${ignored.length} ` +
      "known non-applicable React Router advisory for Declarative BrowserRouter.",
  );
} else {
  console.log("Production dependency audit passed.");
}
