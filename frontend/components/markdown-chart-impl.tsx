"use client";

/**
 * Heavy chart implementations isolated so the parent can lazy-load them.
 * Anything imported here pulls echarts + xviz into the bundle, which is
 * why MarkdownChart wraps this in React.lazy.
 */

import {
  BarChart,
  BigNumber,
  DARK_THEME,
  type DataRecord,
  Funnel,
  Gauge,
  Heatmap,
  LIGHT_THEME,
  LineChart,
  PieChart,
  type QueryData,
  Sankey,
  Scatter,
  Table,
  type Theme,
} from "@minimal-viz/core";
import type { ChartSpec } from "./markdown-chart";

type Props = {
  spec: ChartSpec;
  themeName: "light" | "dark";
};

// Default chart canvas. xviz expects explicit width/height; chat bubble
// width is bounded by parent CSS, so we pin to a sane height and let
// width be 100% of the bubble.
const DEFAULT_HEIGHT = 280;

export function ChartLoader({ spec, themeName }: Props) {
  const theme: Theme = themeName === "dark" ? DARK_THEME : LIGHT_THEME;
  // Coerce raw rows to DataRecord (string|number|boolean|null values).
  // The chart libs are strict about the union; for now we trust the LLM
  // to emit primitives and stringify the odd object as a defensive net.
  const data: DataRecord[] = (spec.data ?? []).map((row) => {
    const out: DataRecord = {};
    for (const [k, v] of Object.entries(row)) {
      if (
        typeof v === "string" || typeof v === "number" ||
        typeof v === "boolean" || v === null
      ) {
        out[k] = v;
      } else {
        out[k] = String(v);
      }
    }
    return out;
  });
  const queriesData: QueryData[] = [{ data }];
  // xviz formData = the spec minus our bookkeeping fields (data, title).
  const { data: _omitData, title: _omitTitle, ...formData } = spec;
  void _omitData;
  void _omitTitle;

  // Common props for chart components — width/height + theme + the
  // chart-specific formData. Each chart picks its own viz type.
  const common = {
    width: 760,
    height: DEFAULT_HEIGHT,
    queriesData,
    theme,
    // xviz infers viewport from container; fluid width via CSS:
    style: { width: "100%", maxWidth: "100%" } as React.CSSProperties,
  };

  switch (spec.vizType) {
    case "pie":
      return <PieChart {...common} formData={formData as never} />;
    case "bar":
      return <BarChart {...common} formData={formData as never} />;
    case "line":
      return <LineChart {...common} formData={formData as never} />;
    case "table":
      return <Table {...common} formData={formData as never} />;
    case "big-number":
      return <BigNumber {...common} formData={formData as never} />;
    case "scatter":
      return <Scatter {...common} formData={formData as never} />;
    case "heatmap":
      return <Heatmap {...common} formData={formData as never} />;
    case "sankey":
      return <Sankey {...common} formData={formData as never} />;
    case "funnel":
      return <Funnel {...common} formData={formData as never} />;
    case "gauge":
      return <Gauge {...common} formData={formData as never} />;
    default:
      return (
        <div
          className="rounded-md border px-3 py-2 text-[12px]"
          style={{
            backgroundColor: "var(--app-status-warn-bg)",
            borderColor: "var(--app-status-warn-card-border)",
            color: "var(--app-status-warn-fg)",
          }}
        >
          未支持的 vizType: {spec.vizType}
        </div>
      );
  }
}
