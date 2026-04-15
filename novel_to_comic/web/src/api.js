/** Typed API client for the Canary dashboard. */
const BASE = "/api";
async function json(url, init) {
    const res = await fetch(url, init);
    if (!res.ok) {
        const text = await res.text();
        throw new Error(`${res.status}: ${text}`);
    }
    return res.json();
}
// ── Projects ────────────────────────────────────────────────────────────────
export function listProjects() {
    return json(`${BASE}/projects/`);
}
export function getStatus(project) {
    return json(`${BASE}/projects/${project}/status`);
}
// ── Pipeline ────────────────────────────────────────────────────────────────
export function runPipeline(project, stage) {
    const url = stage
        ? `${BASE}/projects/${project}/run?stage=${stage}`
        : `${BASE}/projects/${project}/run`;
    return json(url, { method: "POST" });
}
export function approveStage(project, stage) {
    return json(`${BASE}/projects/${project}/approve/${stage}`, { method: "POST" });
}
// ── Pages ───────────────────────────────────────────────────────────────────
export function listPages(project) {
    return json(`${BASE}/projects/${project}/pages/`);
}
export function getPage(project, pageNum) {
    return json(`${BASE}/projects/${project}/pages/${pageNum}`);
}
export function updatePage(project, pageNum, patch) {
    return json(`${BASE}/projects/${project}/pages/${pageNum}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
    });
}
export function pagePreviewUrl(project, pageNum) {
    return `${BASE}/projects/${project}/pages/${pageNum}/preview`;
}
export function pageThumbnailUrl(project, pageNum) {
    return `${BASE}/projects/${project}/files/assembly/pages/page_${String(pageNum).padStart(3, "0")}.png`;
}
// ── Export ───────────────────────────────────────────────────────────────────
export function triggerExport(project, format = "pdf") {
    return json(`${BASE}/projects/${project}/export/?format=${format}`, { method: "POST" });
}
export function exportDownloadUrl(project, format) {
    return `${BASE}/projects/${project}/export/${format}`;
}
// ── Config ──────────────────────────────────────────────────────────────────
export function getConfig(project) {
    return json(`${BASE}/projects/${project}/config/`);
}
export function updateConfig(project, patch) {
    return json(`${BASE}/projects/${project}/config/`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
    });
}
// ── SSE ─────────────────────────────────────────────────────────────────────
export function eventStreamUrl(project) {
    return `${BASE}/projects/${project}/events`;
}
