import React, { useEffect, useState } from "react";
import { listDatasets } from "../api.js";
import { fmtBytes, hashLabel, summariseDatasets } from "../datasets.js";
import { provenanceSections } from "../provenance.js";
import { Caveat, Chip, DataTable, Empty } from "../ui/index.jsx";

/**
 * Provenance tab — what produced this run's numbers.
 *
 * Every row is read off GET /runs/{id}/result and names the field it came
 * from, so the table is emitted by the run that produced the numbers rather
 * than maintained by hand beside them. The honesty labels the run carries
 * (synthetic, modified terrain, an unverified regression, an out-of-population
 * dam class, an unpublished damage curve, boundary-shaped and minority gauges)
 * each get a Caveat here in the same tone they carry elsewhere.
 *
 * A field the run did not record says "not recorded for this run". Runs written
 * before a field existed are in the shipped database and still load; a blank
 * cell would read as "nothing to report", which is a different claim.
 */
export default function ProvenancePanel({ result, active }) {
  if (!result) {
    return (
      <div className="jr-page">
        <Empty inline>Run or load a simulation to see where its numbers came from.</Empty>
        <DatasetsSection active={active} />
      </div>
    );
  }

  const sections = provenanceSections(result);

  return (
    <div className="jr-page">
      <h3 className="jr-h1">Provenance — {result.dam_name}</h3>
      <p className="jr-lede jr-measure">
        Every row below is a field of this run's own result payload, named in
        the right-hand column. Nothing here is typed in after the fact.
      </p>

      {sections.map((section) => (
        <section key={section.id} className="jr-section jr-measure-wide">
          <h4 className="jr-h2">{section.title}</h4>
          {section.caveats.map((c) => (
            <Caveat key={c.title} tone={c.tone} title={c.title} className="jr-measure jr-mb-12">
              {c.body && <div>{c.body}</div>}
            </Caveat>
          ))}
          <DataTable compact kv>
            <tbody>
              {section.rows.map((r) => (
                <tr key={r.path + r.label}>
                  <td>{r.label}</td>
                  <td className={r.missing ? "muted" : undefined}>{r.value}</td>
                  <td className="file">{r.path}</td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        </section>
      ))}

      <DatasetsSection active={active} />
    </div>
  );
}

/**
 * What data is on the machine the API runs on.
 *
 * Fetched when this tab is first opened rather than at app start: it walks the
 * data directory, and nothing should pay for that until someone looks. A row
 * exists only if the file exists, so an expected-but-absent dataset is simply
 * not here — which is the answer an operator needs before going offline.
 */
function DatasetsSection({ active }) {
  const [payload, setPayload] = useState(null);
  const [error, setError] = useState(null);
  const [asked, setAsked] = useState(false);

  useEffect(() => {
    if (!active || asked) return;
    setAsked(true);
    listDatasets().then(setPayload).catch((err) => setError(String(err.message || err)));
  }, [active, asked]);

  // sha256 is computed off the request thread; one re-fetch picks up the
  // finished values rather than polling.
  useEffect(() => {
    if (payload?.hashing?.status !== "running") return undefined;
    const id = setTimeout(() => {
      listDatasets().then(setPayload).catch(() => {});
    }, 5000);
    return () => clearTimeout(id);
  }, [payload]);

  if (error) {
    return (
      <section className="jr-section jr-measure-wide">
        <h4 className="jr-h2">Datasets on this machine</h4>
        <Caveat title="The catalogue could not be read">{error}</Caveat>
      </section>
    );
  }
  if (!payload) {
    return (
      <section className="jr-section jr-measure-wide">
        <h4 className="jr-h2">Datasets on this machine</h4>
        <Empty inline>{active ? "Reading the data directory…" : "Opens with this tab."}</Empty>
      </section>
    );
  }

  const summary = summariseDatasets(payload);
  return (
    <section className="jr-section jr-measure-wide">
      <h4 className="jr-h2">Datasets on this machine</h4>
      <p className="jr-lede">
        {summary.fileCount} files, {fmtBytes(summary.totalBytes)}, under{" "}
        <code>{summary.dataDir}</code>. A row exists only if the file exists —
        nothing here is a dataset the system would fetch.
      </p>

      {summary.forbidden.length > 0 && (
        <Caveat tone="danger" title="A file here must not be redistributed">
          {summary.forbidden.map((row) => (
            <div key={row.path}>
              {row.path} — {row.redistribution_reason}
            </div>
          ))}
        </Caveat>
      )}

      {summary.superseded.length > 0 && (
        <Caveat title={`${summary.superseded.length} superseded raster(s) still on disk`}>
          Written before the 2026-09-06 Earth Engine aggregation fix. They are
          listed because they are still here and runs that used them are still
          in the database; their population totals are low by the square of the
          ratio between the solver grid and 100 m.
        </Caveat>
      )}

      <DataTable compact className="jr-mt-8">
        <thead>
          <tr>
            <th>Product family</th>
            <th className="num">Files</th>
            <th className="num">Size</th>
            <th>Agency</th>
            <th>Licence</th>
          </tr>
        </thead>
        <tbody>
          {/* Engines are programs, not files: listing them here read as
              "2 files, 0 B". They have their own section below. */}
          {summary.families.filter((f) => f.family !== "engine").map((family) => (
            <tr key={family.family}>
              <td>{family.label}</td>
              <td className="num">{family.count}</td>
              <td className="num">{fmtBytes(family.bytes)}</td>
              <td className="muted">{family.rows[0]?.agency}</td>
              <td className="muted">{family.rows[0]?.licence}</td>
            </tr>
          ))}
        </tbody>
      </DataTable>

      <h4 className="jr-h2">Engines</h4>
      <DataTable compact kv>
        <tbody>
          {(summary.families.find((f) => f.family === "engine")?.rows || []).map((row) => (
            <tr key={row.name}>
              <td>{row.name}</td>
              <td>
                <Chip tone={row.present ? "ok" : "warn"}>
                  {row.present ? "present" : "absent"}
                </Chip>{" "}
                <span className="muted">{row.note}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </DataTable>

      <h4 className="jr-h2">Largest files, with their checksums</h4>
      <DataTable compact>
        <thead>
          <tr>
            <th>Path</th>
            <th className="num">Size</th>
            <th>Fetched</th>
            <th>sha256</th>
          </tr>
        </thead>
        <tbody>
          {summary.families
            .flatMap((family) => family.rows)
            .filter((row) => row.bytes != null)
            .sort((a, b) => b.bytes - a.bytes)
            .slice(0, 10)
            .map((row) => {
              const hash = hashLabel(row, summary.hashing);
              return (
                <tr key={row.path}>
                  <td className="file" title={row.note || ""}>
                    {row.path}
                    {row.superseded ? <span className="muted"> · superseded</span> : null}
                  </td>
                  <td className="num">{fmtBytes(row.bytes)}</td>
                  <td className="muted">{row.fetched_at || row.modified_at || "—"}</td>
                  <td className={hash.pending ? "file muted" : "file"} title={hash.full || ""}>
                    {hash.text}
                  </td>
                </tr>
              );
            })}
        </tbody>
      </DataTable>

      <p className="jr-note">
        sha256 is computed off the request thread and cached by path, size and
        modification time —{" "}
        {summary.hashing?.status === "running"
          ? `${summary.hashing.pending} file(s) still to hash; this table fills in as they finish.`
          : "every listed file has been hashed."}
      </p>
    </section>
  );
}
