// Thin fetch wrapper around the JalRaksha FastAPI service (brief §5.1).
const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

// Endpoints return export/keyframe/comparison-image paths as "/files/..."
// (served by the API's static mount, services/api/jalraksha_service/main.py)
// rather than full URLs — resolve them against the API origin here.
export function resolveApiUrl(pathOrUrl) {
  if (!pathOrUrl) return pathOrUrl;
  return /^https?:\/\//.test(pathOrUrl) ? pathOrUrl : `${API}${pathOrUrl}`;
}

export async function listDams() {
  const r = await fetch(`${API}/dams`);
  return r.json();
}

export async function submitRun(req) {
  const r = await fetch(`${API}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  return r.json();
}

export async function getRun(runId) {
  const r = await fetch(`${API}/runs/${runId}`);
  return r.json();
}

export async function getResult(runId) {
  const r = await fetch(`${API}/runs/${runId}/result`);
  if (!r.ok) throw new Error(`Run not done (${r.status})`);
  return r.json();
}

export async function getGauges(runId) {
  const r = await fetch(`${API}/gauges/${runId}`);
  return r.json();
}

export async function getComparison(runId) {
  const r = await fetch(`${API}/runs/${runId}/comparison`);
  return r.json();
}

export async function getSar(reach = "bhagirathi") {
  const r = await fetch(`${API}/gee/latest?reach=${reach}`);
  return r.json();
}

// Poll until a run reaches a terminal state.
export async function pollUntilDone(runId, onTick, timeoutMs = 600000) {
  const start = Date.now();
  // eslint-disable-next-line no-constant-condition
  while (true) {
    const s = await getRun(runId);
    onTick?.(s);
    if (s.status === "done" || s.status === "failed") return s;
    if (Date.now() - start > timeoutMs) throw new Error("Run timed out");
    await new Promise((r) => setTimeout(r, 2000));
  }
}

// Ask the API to launch the ParaView desktop GUI for a run (3D terrain + flood).
//
// Only meaningful when the API runs on the same machine as this browser — it
// opens a window on the API's host, not the client's. The endpoint answers with
// a structured {launched, reason, detail} rather than an HTTP error for its
// operational failures (no dataset, ParaView missing), because those are
// expected states a user needs to read, not exceptions. Genuine HTTP errors
// (404 unknown run) still surface as thrown Errors carrying FastAPI's `detail`.
export async function openInParaview(runId) {
  const r = await fetch(`${API}/runs/${runId}/open-paraview`, { method: "POST" });
  let body = null;
  try {
    body = await r.json();
  } catch {
    body = null;
  }
  if (!r.ok) {
    throw new Error(body?.detail || `ParaView launch failed (HTTP ${r.status})`);
  }
  return body;
}
