import React from "react";
import { provenanceSections } from "../provenance.js";
import { Caveat, DataTable, Empty } from "../ui/index.jsx";

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
export default function ProvenancePanel({ result }) {
  if (!result) {
    return <Empty>Run or load a simulation to see where its numbers came from.</Empty>;
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
    </div>
  );
}
