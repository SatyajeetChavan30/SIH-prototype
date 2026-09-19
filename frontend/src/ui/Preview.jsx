import React, { useState } from "react";
import {
  Button, Card, Caveat, Chip, DataTable, Empty, SectionLabel, Stat, TabPill,
} from "./index.jsx";
import { APP_NAME, APP_TAGLINE } from "./brand.js";

/**
 * Development-only gallery of the primitives, opened with `?ui-preview` on the
 * dev server (main.jsx gates it on import.meta.env.DEV, so a production build
 * drops it). Every figure below is sample text, not a model result.
 *
 * Its main job is the Caveat row: one of each honesty label the dashboard
 * carries, so their contrast and size can be checked in one place.
 */
export default function Preview() {
  const [tab, setTab] = useState("gauges");
  const tabs = [
    ["workspace", "2D + 3D"], ["gauges", "Gauges", 7], ["ensemble", "Ensemble"],
    ["downloads", "Downloads", 24],
  ];
  return (
    <div className="jr" style={{ minHeight: "100vh" }}>
      <div className="jr-topbar">
        <span className="jr-brand__mark">{APP_NAME}</span>
        <span className="jr-brand__tag">{APP_TAGLINE}</span>
        <div role="tablist" style={{ display: "flex", gap: 6, marginLeft: 16 }}>
          {tabs.map(([id, label, badge]) => (
            <TabPill key={id} active={tab === id} badge={badge} onClick={() => setTab(id)}>
              {label}
            </TabPill>
          ))}
        </div>
        <div className="jr-topbar__status">
          <Chip mono>e2e09ea3</Chip> sample run
        </div>
      </div>

      <div className="jr-page jr-stack" style={{ height: "auto" }}>
        <h1 className="jr-h1">UI primitives (sample content)</h1>

        <SectionLabel>Caveats — every honesty label</SectionLabel>
        <div className="jr-stack jr-measure-wide" data-testid="caveats">
          <Caveat tone="danger" strip title="SYNTHETIC — NOT A REAL SIMULATION">
            No solver ran. A prescribed wave was painted onto the Copernicus DEM for
            the long-reach picture only.
          </Caveat>
          <Caveat strip title="Terrain modified — observation-conditioned DEM update.">
            Base: Copernicus GLO-30. <strong>This is not photogrammetry and not a survey
            product.</strong> (JALRAKSHA_NOT_A_SURVEY)
          </Caveat>
          <Caveat title="Screening figure only — dam class outside fitted population">
            The breach regressions were fitted on embankment dams.
          </Caveat>
          <Caveat title="Unverified regression in this ensemble">
            xu_zhang_2009 is quarantined pending coefficient transcription.
          </Caveat>
          <Caveat compact>1 of 4 members arrived here — a minority arrival, not a median.</Caveat>
          <Caveat compact>
            3.0 km from the domain edge — depth shaped by the outflow boundary, not a
            clean measurement.
          </Caveat>
          <Caveat tone="info">
            Tier-1 screening output from 30 m Copernicus GLO-30 — lead with arrival
            times and inundation extent; point depths are indicative only.
          </Caveat>
          <Caveat tone="ok" title="Engine: Delft3D FM (dflowfm-cli, dimrset 2026.01)">
            The official Deltares kernel produced the depth field.
          </Caveat>
        </div>

        <SectionLabel>Stats</SectionLabel>
        <div className="jr-row">
          <Stat label="Peak breach outflow" value="41,200" unit="m³/s" size="lg"
                band="18,900 – 77,400 m³/s" hint="5th–95th percentile across the ensemble" />
          <Stat label="Population at risk" value="58,095" emphasis />
          <Stat label="Depth field RMSE" value="0.035 m" accent="#e65100" />
        </div>
        <Stat plain label="Population at risk (sidebar)" value="58,095" />

        <SectionLabel>Chips and buttons</SectionLabel>
        <div className="jr-row" style={{ alignItems: "center" }}>
          <Chip tone="ok">PASS</Chip>
          <Chip tone="danger">FAIL</Chip>
          <Chip tone="warn">running</Chip>
          <Chip tone="info">cached</Chip>
          <Chip count>24</Chip>
          <Chip mono>e2e09ea3</Chip>
          <Button variant="primary">Run dam-break simulation</Button>
          <Button>Load</Button>
          <Button size="sm">Small</Button>
          <Button variant="primary" disabled>Disabled</Button>
        </div>

        <Card eyebrow="Card" title="Downstream gauges">
          <DataTable>
            <thead>
              <tr><th>Town</th><th className="num">Distance</th><th className="num">Arrival</th></tr>
            </thead>
            <tbody>
              <tr><td>Deccan Gymkhana</td><td className="num">10.5 km</td><td className="num strong">1h 40m</td></tr>
              <tr><td>Swargate</td><td className="num">11.5 km</td><td className="num muted">—</td></tr>
            </tbody>
          </DataTable>
        </Card>

        <div className="jr-form" style={{ maxWidth: 300 }}>
          <label>Site</label>
          <select><option>Khadakwasla</option></select>
          <label>Height (m): 260</label>
          <input type="range" min="10" max="400" defaultValue="260" />
          <label>Run id</label>
          <input type="text" placeholder="...or paste a run id" />
        </div>

        <Empty>Run a simulation first, or load a run id.</Empty>
      </div>
    </div>
  );
}
