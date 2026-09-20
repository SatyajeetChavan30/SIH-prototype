/**
 * Reading the dataset catalogue.
 *
 * The server lists only files that exist (services/api/jalraksha_service/
 * datasets.py); this groups them for display and keeps two labels honest:
 *
 *  - a SUPERSEDED product is still listed, because it is still on disk and a
 *    run that used it is still in the database;
 *  - a FORBIDDEN-licence row is called out rather than folded into a total,
 *    since these rows are what a data pack would carry.
 *
 * Pure (no React) so `node --test` can pin it.
 */

export const FAMILY_LABELS = {
  dem_copernicus: "Copernicus DEM GLO-30",
  dem_updated: "Observation-conditioned DEM (not a survey)",
  ghsl: "GHSL population and built-up surface",
  worldcover: "ESA WorldCover land cover",
  sentinel1: "Sentinel-1 derived water",
  engine: "Solver engines on this machine",
  unknown: "Unclassified",
};

export function fmtBytes(bytes) {
  if (bytes == null) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = Number(bytes);
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value < 10 && unit > 0 ? value.toFixed(1) : Math.round(value)} ${units[unit]}`;
}

/** Group the rows by product family, newest-looking first is NOT implied. */
export function summariseDatasets(payload) {
  const rows = payload?.rows || [];
  const byFamily = new Map();
  for (const row of rows) {
    const key = row.family || "unknown";
    const entry = byFamily.get(key) || { family: key, label: FAMILY_LABELS[key] || key, count: 0, bytes: 0, rows: [] };
    entry.count += 1;
    entry.bytes += row.bytes || 0;
    entry.rows.push(row);
    byFamily.set(key, entry);
  }
  return {
    families: [...byFamily.values()].sort((a, b) => b.bytes - a.bytes),
    totalBytes: payload?.total_bytes ?? rows.reduce((sum, r) => sum + (r.bytes || 0), 0),
    fileCount: rows.filter((r) => r.bytes != null).length,
    superseded: rows.filter((r) => r.superseded),
    forbidden: rows.filter((r) => r.redistribution === "forbidden"),
    hashing: payload?.hashing || null,
    dataDir: payload?.data_dir || null,
  };
}

/** Wording for the sha256 column, which is filled in the background. */
export function hashLabel(row, hashing) {
  if (row?.sha256) return { text: `${row.sha256.slice(0, 12)}…`, pending: false, full: row.sha256 };
  if (row?.bytes == null) return { text: "—", pending: false, full: null };
  const running = hashing?.status === "running" || hashing?.status === "pending";
  return {
    text: running ? "computing…" : "not hashed",
    pending: running,
    full: null,
  };
}
