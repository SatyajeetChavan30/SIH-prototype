/**
 * Chart theming for recharts.
 *
 * Chrome — axis text, grid lines, legend text — is styled in styles/ui.css
 * under .jr .recharts-*: CSS outranks SVG presentation attributes, so no
 * per-chart stroke or font props are needed. What CSS cannot reach is here:
 * the tooltip (an HTML div recharts styles inline) and legend placement.
 *
 * SERIES holds DATA colours: which engine drew which line. They are the values
 * the panels already used, gathered so Validation, Ensemble and SPH agree, and
 * they are not part of the chrome palette. FD2320 hazard colours are NOT here
 * — they come from the run payload.
 */
export const SERIES = {
  // Engines, wherever they are compared.
  jalraksha: "#1565C0",
  delft3d: "#e65100",
  exact: "#111",
  errorBar: "#7a3e00",
  // A chart's first and second quantity when no engine is involved (the
  // stage-storage curve, the SPH front and particle cloud).
  primary: "#1565C0",
  secondary: "#e65100",
};

export const TOOLTIP_PROPS = {
  contentStyle: {
    borderRadius: 8,
    border: "1px solid #e6e6e6",
    boxShadow: "0 2px 6px rgba(0, 0, 0, 0.08)",
    fontSize: 13,
    fontFamily: "inherit",
  },
  labelStyle: { color: "#242424", fontWeight: 500 },
  itemStyle: { padding: 0 },
};

/**
 * Legend at the TOP. At the bottom it shared the chart's bottom margin with the
 * x-axis label and the two drew over each other ("Surge front" across
 * "time (s)", the Ritter legend across its distance label).
 */
export const LEGEND_PROPS = {
  verticalAlign: "top",
  height: 28,
};
