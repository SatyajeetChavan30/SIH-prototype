import React, { useEffect, useState } from "react";
import { listRegistry } from "../api.js";
import { demLabel, frlLabel, tierBadge } from "../registry.js";
import { Caveat, Chip, DataTable, Empty } from "../ui/index.jsx";

/**
 * Registry — the sites this install can model, and how it knows.
 *
 * Readiness is computed server-side from three checkable facts (a staged DEM
 * that covers the domain, the gauges the preset carries, the runs that
 * finished with exports), so every badge here answers "how do you know?" with
 * a function rather than a claim typed into a table.
 *
 * Selecting a row sets the active site for the control panel. It does NOT
 * start a run.
 */
export default function RegistryPanel({ onSelectSite, selectedId }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    listRegistry()
      .then((data) => !cancelled && setRows(data))
      .catch((err) => !cancelled && setError(String(err.message || err)));
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return (
      <div className="jr-page">
        <Caveat title="The registry could not be read">{error}</Caveat>
      </div>
    );
  }
  if (!rows) return <Empty>Reading the registry…</Empty>;
  if (!rows.length) return <Empty>No sites are configured on this install.</Empty>;

  return (
    <div className="jr-page">
      <h3 className="jr-h1">Registry — what this install can model</h3>
      <p className="jr-lede jr-measure">
        Four sites, and only four: the ones with cached terrain, gauge geometry
        and completed runs behind them. A badge below is computed at request
        time from files on this machine and rows in this database — none of it
        is typed in. Selecting a row sets the active site; it does not start a
        run.
      </p>

      <DataTable className="jr-measure-wide">
        <thead>
          <tr>
            <th>Site</th>
            <th>River / state</th>
            <th className="num">Gauges</th>
            <th className="num">Runs</th>
            <th>Terrain</th>
            <th>Full reservoir level</th>
            <th>Readiness</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const badge = tierBadge(row);
            const dem = demLabel(row);
            const frl = frlLabel(row);
            return (
              <tr key={row.id}>
                <td>
                  <button
                    type="button"
                    className="jr-linkish"
                    aria-pressed={row.id === selectedId}
                    onClick={() => onSelectSite?.(row.id)}
                  >
                    <strong>{row.name}</strong>
                  </button>
                  {/* The preset's own barrier_source already opens with
                      HYPOTHETICAL; prefixing it again read as a stutter. */}
                  {row.hypothetical && (
                    <Caveat compact className="jr-row-note" tone="warn">
                      {row.barrier?.barrier_source}
                    </Caveat>
                  )}
                  {row.record_type === "blockage" && !row.hypothetical && (
                    <span className="muted"> · blockage site</span>
                  )}
                </td>
                <td>
                  {row.river || "—"}
                  {row.state ? <span className="muted"> · {row.state}</span> : null}
                </td>
                <td className="num">{row.gauge_count}</td>
                <td className="num">{row.runs?.completed ?? 0}</td>
                <td className={dem.ok ? undefined : "muted"} title={dem.detail}>
                  {dem.text}
                </td>
                <td className={frl.value == null ? "muted" : undefined} title={frl.source}>
                  {frl.text}
                </td>
                <td>
                  <Chip tone={badge.tone} title={badge.reason}>
                    {badge.label}
                  </Chip>
                </td>
              </tr>
            );
          })}
        </tbody>
      </DataTable>

      <p className="jr-note jr-measure jr-mt-16">
        A cached DEM is not the same as a covered domain: tiles are fetched as
        windows but cached under the full tile's name, so the check reads the
        raster's own bounds against the domain box, widened by the diagonal
        because a square domain reaches its radius times root two at the
        corners.
      </p>
    </div>
  );
}
