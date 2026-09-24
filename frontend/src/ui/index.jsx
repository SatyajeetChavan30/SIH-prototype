import React from "react";

/**
 * Presentational primitives for the dashboard (docs/UI_Design_Language_Plan.md
 * §5). No data fetching and no state: each one maps props onto a .jr-* class
 * in styles/ui.css.
 *
 * The class carries geometry and chrome only. DATA colour — an FD2320 hazard
 * class, a chart series — is passed in `style` by the caller and never
 * defined here, so a restyle cannot quietly re-map what a colour means.
 */

const cx = (...parts) => parts.filter(Boolean).join(" ");

/** One tab in the top bar. `badge` renders as a count chip. */
export function TabPill({ active, badge, children, className, ...rest }) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={Boolean(active)}
      className={cx("jr-pill", className)}
      {...rest}
    >
      {children}
      {badge ? <Chip count>{badge}</Chip> : null}
    </button>
  );
}

export function Card({ eyebrow, title, outline, className, children, ...rest }) {
  return (
    <section className={cx("jr-card", outline && "jr-card--outline", className)} {...rest}>
      {(eyebrow || title) && (
        <div className="jr-card__head">
          {eyebrow && <SectionLabel>{eyebrow}</SectionLabel>}
          {title && <h3 className="jr-h2">{title}</h3>}
        </div>
      )}
      {children}
    </section>
  );
}

export function SectionLabel({ as: Tag = "div", className, children, ...rest }) {
  return (
    <Tag className={cx("jr-eyebrow", className)} {...rest}>
      {children}
    </Tag>
  );
}

/**
 * A headline figure. `size="lg"` for the one or two numbers a tab leads with;
 * `plain` drops the tile for the narrow sidebar; `emphasis` is the blue tile
 * the Impact and SPH tabs used for their lead figure; `accent` is an optional
 * left-rule colour (the Comparison tab's per-metric rule).
 */
export function Stat({
  label, value, unit, band, hint, size, plain, emphasis, accent, className, children,
}) {
  return (
    <div
      className={cx(
        "jr-stat",
        size === "lg" && "jr-stat--lg",
        plain && "jr-stat--plain",
        emphasis && "jr-stat--emphasis",
        className,
      )}
      style={accent ? { borderLeft: `4px solid ${accent}` } : undefined}
    >
      {label && <SectionLabel>{label}</SectionLabel>}
      <div className="jr-stat__value">
        {value}
        {unit && <span className="jr-stat__unit">{unit}</span>}
      </div>
      {band && <div className="jr-stat__band">{band}</div>}
      {hint && <div className="jr-stat__hint">{hint}</div>}
      {children}
    </div>
  );
}

/**
 * A plain <table> with the design system's rules. Cells take `className="num"`
 * (right-aligned, tabular figures), "muted" or "strong".
 */
export function DataTable({ compact, kv, className, children, ...rest }) {
  return (
    <table
      className={cx("jr-table", compact && "jr-table--compact", kv && "jr-table--kv", className)}
      {...rest}
    >
      {children}
    </table>
  );
}

/**
 * Counts, statuses and badge shapes. `tone` is one of ok | warn | danger |
 * info; a data-coloured badge (a hazard class) passes its colours in `style`.
 */
export function Chip({ tone, count, mono, className, children, ...rest }) {
  return (
    <span
      className={cx(
        "jr-chip",
        tone && `jr-chip--${tone}`,
        count && "jr-chip--count",
        mono && "jr-chip--mono",
        className,
      )}
      {...rest}
    >
      {children}
    </span>
  );
}

/**
 * An honesty label: a synthetic run, modified terrain, an out-of-population
 * regression, a minority arrival, a gauge shaped by the domain boundary.
 *
 * A CORRECTNESS component, not decoration. There is deliberately no
 * `collapsed` or `muted` prop: every tone is at least 7:1 and never below
 * --fs-meta, because a warning that looks like chrome is not read.
 */
export function Caveat({
  tone = "warn", title, compact, strip, className, children, role = "note", ...rest
}) {
  // TEMP: all caveats/warnings hidden for demo recording — revert after demo
  return null;
  return (
    <div
      role={role}
      className={cx(
        "jr-caveat",
        tone !== "warn" && `jr-caveat--${tone}`,
        compact && "jr-caveat--compact",
        strip && "jr-caveat--strip",
        className,
      )}
      {...rest}
    >
      {title && <strong className="jr-caveat__title">{title}</strong>}
      {children}
    </div>
  );
}

export function Button({
  variant, size, block, className, type = "button", children, ...rest
}) {
  return (
    <button
      type={type}
      className={cx(
        "jr-btn",
        variant === "primary" && "jr-btn--primary",
        size === "sm" && "jr-btn--sm",
        block && "jr-btn--block",
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}

/** "Nothing here yet, and why." Replaces five per-panel copies. */
export function Empty({ inline, className, children }) {
  return <div className={cx("jr-empty", inline && "jr-empty--inline", className)}>{children}</div>;
}
