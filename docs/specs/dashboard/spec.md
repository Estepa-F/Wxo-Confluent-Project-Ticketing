# E-Shop Support Portal — Dashboard Refactor Spec

Supersedes the original build spec that produced the current `dashboard.html` (that version shipped with a dark theme, a right-side KPI+donut row below the chart, and a narrow Live Activity feed — this spec replaces that layout with the approved light-theme mockup's information architecture, while keeping every existing widget's underlying logic).

## 0. Goal & constraints

Refactor the existing Support Operations Dashboard (`app/support_portal/static/dashboard.html`) to match the approved light-theme mockup's layout and information architecture, while preserving all current backend behavior and data contracts.

Do not rebuild the app architecture. Do not introduce React, Vue, Tailwind, a bundler, or a build step. Keep the existing static HTML/CSS/vanilla JS approach and the current Chart.js / WebSocket integration (`/ws/dashboard`).

**Before changing anything**, note what's already built (verified directly against the live file — several pieces below only need repositioning, not building):

| Piece | Status |
|---|---|
| 6 service cards (icon, status pill, tickets/min, sparkline) | **Already built**, `dashboard.html:754-786` |
| Volume chart: 6 services × actual+forecast (12 datasets), custom 6-entry legend, time-range presets, incident annotations | **Already built**, `dashboard.html:835-963` |
| KPI cards labeled "Total Tickets" / "Bot Answered" / "Escalated to Human", % computed against `auto_resolved + escalated` | **Already built and already correctly labeled**, `dashboard.html:470-484`, `renderKpis()` at `:1049-1057` |
| Forecast Insight card | **Already built**, `dashboard.html:509-516`, `updateForecastInsight()` at `:1000-1029` — just in the wrong position |
| Service-distribution donut chart | **Exists today** (`#serviceDonut`, `dashboard.html:485-491`) — this spec removes it |
| Live Activity feed | **Exists today** but only shows time/service/action, batched into counts — this spec replaces it with the Live Triage Stream table |

So this refactor is primarily a **layout/repositioning + one new table** task, not a rebuild of the underlying widgets.

## 1. Target layout

```
┌───────────────────────────────────────────────────────────┐
│ HEADER (unchanged: eyebrow, title, subtitle, Live Demo,    │
│ clock, theme toggle, Demo controls button)                 │
├───────────────────────────────────────────────────────────┤
│ SERVICE CARDS × 6, one row (unchanged, already correct)     │
├─────────────────────────────────────────┬───────────────────┤
│ SUPPORT TICKET VOLUME (unchanged chart) │ Total Tickets      │
│                                          │ Bot Answered       │
│                                          │ Escalated to Human │
│                                          │ Forecast Insight   │
│                                          │ Sentiment by Service│
├─────────────────────────────────────────┴───────────────────┤
│ LIVE TRIAGE STREAM — full width, filters + table              │
└───────────────────────────────────────────────────────────────┘
```

Concrete CSS change to `.main-grid` (`dashboard.html:172-181`): replace the current 2-row-in-right-column / 4-wide-KPI-row-in-left-column layout with:
```css
.main-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 300px;
  grid-template-rows: minmax(0, 1.25fr) minmax(0, 1.1fr);
  grid-template-areas:
    "volume  sidebar"
    "triage  triage";
  gap: 10px;
}
.sidebar { grid-area: sidebar; display: flex; flex-direction: column; gap: 10px; min-height: 0; overflow-y: auto; }
.triage-panel { grid-area: triage; }
```
The row split favors the triage row slightly more than a plain 1:1 (chosen empirically — verify visually rather than treating `1.25fr`/`1.1fr` as sacred if content changes) so the Live Triage Stream shows more rows without scrolling. The `.kpi-area`'s internal `repeat(4, 1fr)` grid is removed along with the donut card; the three existing KPI-card `<div class="panel kpi-card">` blocks and the existing Forecast panel move, unchanged internally, into `.sidebar` in the order: Total Tickets, Bot Answered, Escalated to Human, Forecast Insight. Sentiment by Service is no longer part of the sidebar — see §3a.

The 4 sidebar cards use `flex: 1 1 auto` (not `0 0 auto`) with a small explicit `min-height` each (`.kpi-card` 72px, `.forecast-panel` 84px) so they stretch to fill the sidebar's full height with no dead space below Forecast Insight. The explicit `min-height` matters, not just cosmetically: `.panel` has `overflow: hidden`, and per the flexbox spec a flex item with non-visible overflow gets an *automatic minimum size of 0* — combined with `flex-basis: 0` (i.e. `flex: 1 1 0`) this makes nested-flex-in-grid intrinsic sizing collapse unpredictably (confirmed while building this: the sidebar row shrank to ~26px per card at the narrow breakpoint, silently clipping label/subtext). Use `flex: 1 1 auto` + an explicit floor, not `flex: 1 1 0`.

Narrow-width fallback (mirror the existing `@media` block at `dashboard.html:390-395`): stack `volume`/`sidebar`/`triage` as three full-width rows (`grid-template-rows: auto minmax(440px, auto) auto`). The sidebar row needs an explicit `minmax` floor, not plain `auto` — with `flex: 1 1 auto` sidebar children now stretching, `auto`'s content-based sizing at this breakpoint isn't reliable (see above). This breakpoint also overrides `.app { height: auto; min-height: 100vh; }` (base rule is `height: 100vh`, which combined with `.main-grid`'s `min-height: 0` clamps *all* grid rows to whatever's left after the header/cards instead of letting the page grow and scroll — the existing `html, body { overflow-y: auto; }` in this block only works once `.app` itself is allowed to grow past the viewport).

## 2. Header — unchanged

No changes. Keep the existing eyebrow/title/subtitle, Live Demo pill + clock, theme toggle, and "Demo controls" button exactly as they are.

## 3. Service cards

Icon, service name, status pill (Healthy=green / Degraded=amber / Down=red via `.health-operational`/`.health-degraded`/`.health-outage`), `tickets/min` rate, sparkline, one row of 6 at normal desktop widths (3×2 under the `<1500px` breakpoint) — unchanged.

### 3a. Sentiment by Service — moved here from the sidebar
Each card gets a new `.service-sentiment` row below the rate/sparkline row: a "Sentiment" label + percentage text (`sentimentPct-${service}`) and the existing 3-segment bar (`sentimentBar-${service}`, `.sentiment-bar`/`.seg-positive`/`.seg-neutral`/`.seg-negative`), built directly into `buildServiceCards()`'s per-card template instead of a separate `buildSentimentRows()`/`#sentimentRows` sidebar list (which is removed). No change to `renderSentimentRow()`'s logic or its call sites — only the DOM location of the elements it targets. Six cards means all 6 services are always visible with no scrolling, which was the point of moving this out of the 300px sidebar.

The Positive/Neutral/Negative dot legend (`.sentiment-legend`) moves too: one shared instance renders once, in a small caption row directly under `#serviceCards` (`#serviceCardsSentimentLegend`), instead of being repeated inside a sidebar panel.

## 4. Volume chart — unchanged

No functional changes. Already renders 6 individual actual+forecast line pairs (not aggregated), dashed forecast matching each service's solid-line color, a legend with 6 entries (not 12 — built-in legend already disabled, custom legend already built), working Live/15m/1h/12h/1d presets, and incident annotation lines (amber=degraded, red=down). Only the *position* of this panel in the grid changes (`grid-area: volume`, same as today).

## 5. Sidebar — reordered, donut removed, sentiment moved out

Order, top to bottom: **Total Tickets → Bot Answered → Escalated to Human → Forecast Insight**. Sentiment by Service now lives in the service cards instead (§3a) — with 6 services, the sidebar's 300px width made a 6-row sentiment panel cramped/scrolling, so it was relocated to the guaranteed-6-wide card grid above.

### 5.1 Total Tickets, Bot Answered, Escalated to Human
Move the three existing `.kpi-card` panels (`dashboard.html:470-484`) into `.sidebar`, stacked vertically instead of in a 4-wide row. No content/logic changes — labels, values, and percentage-of-actioned math (`renderKpis()`, `dashboard.html:1049-1057`) are already correct (e.g. "Bot Answered" is already the label, not "Auto-resolved"; percentages are already computed against `auto_resolved + escalated`, not `total_tickets`). Compact single-column card styling instead of the current one-of-four-in-a-row width.

### 5.2 Forecast Insight
Move the existing `.forecast-panel` (`dashboard.html:509-516`) into `.sidebar`, positioned after Escalated and before Sentiment. No logic changes — `updateForecastInsight()` (`dashboard.html:1000-1029`) already produces "Projected N% increase/decrease" (green for decrease, red for increase) or "Forecast warming up…" with no data. This card's own comment (`:996-998`) notes its number is a client-side aggregate, never sent to or stored by the backend — keep it that way.

### 5.3 Remove the donut chart
Delete: the `.donut-card` HTML block (`dashboard.html:485-491`), `renderDonut()` and its call site in `handleEnriched()` (`:1072-1083`, `:1204`), the `#donutTotal`/`#donutLegend` elements, and the `.donut-card`/`.donut-chart-wrap`/`.donut-legend*` CSS rules. Do not leave an empty panel — the sidebar simply has 5 cards, not 6.

## 6. Live Triage Stream (replaces Live Activity)

Full-width panel (`grid-area: triage`) below the chart+sidebar row. Read-only: rows are not clickable, no drawers, no details page, no row actions.

### Data source — already available, no backend change required
The current `agent_action` WebSocket message (`dashboard/service.py`'s `handle_message`, the `tickets.agent-actions` branch) already carries everything this table needs in one payload: `ticket_id`, `service`, `text` (raw ticket text, passthrough from `tickets.enriched`'s `SELECT *`), `sentiment_analysis` (nested, same passthrough), and `action`/`message` (already derived server-side via `parse_agent_response()`). The current frontend (`pushActivity()`, `dashboard.html:1122-1158`) simply discards `ticket_id`/`sentiment_analysis`/`text` when building the old narrow feed — this is a frontend-only gap.

**Optional, non-blocking backend enhancement**: for consistency with how the `enriched` message already flattens `sentiment_analysis.sentiment[0].label` into a plain lowercase `sentiment` string (`dashboard/service.py`'s `enriched` branch), consider adding the same one-line extraction to the `agent_action` branch too, so the frontend doesn't have to duplicate that normalization logic in JS. Not required — the frontend can do this extraction itself using the same rule (lowercase, treat `"unknown"` as absent) if the backend change is skipped for now.

### Columns
Time, Ticket ID, Service, Sentiment, Action, Ticket (one-line, ellipsis-truncated: `white-space: nowrap; overflow: hidden; text-overflow: ellipsis`).

### Sentiment display
Icon + text: Positive (green), Neutral (gray/amber), Negative (red). Reuse the same sentiment-color convention already used in the Sentiment-by-Service panel's legend (`--green`/`--amber`/`--red`).

### Action display
Only two states: **Bot answered** (green) / **Escalated** (red) — driven by the same `action` field (`auto_resolve`/`escalate`) already produced by `parse_agent_response()`. Do not show raw Kafka/pipeline metadata.

### Filters
Three compact dropdowns above the table, no reset button (clear via each dropdown's "All ..." option): Service (All services + the 6 services), Sentiment (All sentiments / Positive / Neutral / Negative), Action (All actions / Bot answered / Escalated). Filtering is client-side over the currently buffered events.

### Buffer behavior
Stop batching (the current `ACTIVITY_BATCH_MS` count-merging goes away — one row per real event now). Newest event at the top. Cap the buffer at ~20 events; when a new one arrives past the cap, drop the oldest. Fixed-height panel with internal scrolling if 20 rows exceed available height — the page itself must not grow unbounded. Footer caption: "Showing latest 20 tickets · Auto-updating".

### Suggested JS structure (mirrors the existing file's function-per-concern style)
```js
let triageEvents = [];              // normalized, capped buffer
function normalizeTriageEvent(raw) { ... }   // one place that knows backend field names
function pushTriageEvent(raw) { ... }        // normalize, prepend, cap at 20, re-render
function applyTriageFilters() { ... }        // pure function over triageEvents + current filter state
function renderTriageStream() { ... }        // DOM only, no backend-shape knowledge
```
Wire `pushTriageEvent` into the existing `agent_action` dispatch branch (`dashboard.html:1300`) alongside (not instead of) whatever else that branch already does (KPI counters, etc. — unaffected by this change).

### Normalized event shape (frontend-internal)
```js
{
  timestamp: "12:15:19",
  ticket_id: "TK-10483",       // display as shortId-style, see below
  service: "payments",
  sentiment: "negative",       // "positive" | "neutral" | "negative", or null
  action: "escalated",         // "bot_answered" | "escalated"
  ticket_text: "My payment keeps failing even though my card is valid…",
}
```
Ticket IDs in this system are UUIDs, not sequential numbers like the mockup's `#TK-10483` — reuse the same short-form convention already used elsewhere (`ticket-detail.html`/`tickets.html`'s `shortId()`: `#` + first 5 hex chars of the UUID, uppercased) rather than inventing a new numbering scheme.

## 7. Empty / disconnected states

Never show `NaN`/`undefined`/`null`/a raw exception. Use:
- No triage events yet: "Waiting for triage activity…"
- No forecast yet: "Forecast warming up…" (already implemented)
- No sentiment for a service: "no data yet" (per §3a, now shown inside that service's card)
- No ticket volume yet: "Waiting for ticket activity…" (already implemented, `#incidentCaption`)
- WebSocket disconnected: "Reconnecting…" (verify current reconnect-state UI already says this)

## 8. Explicitly preserve

Theme toggle, "Demo controls" drawer, service status updates, WebSocket reconnect logic, current KPI/forecast/sentiment computation, chart time-range controls, incident annotations. None of these are touched by this refactor beyond being moved to a new grid position.

## 9. Theming

`dashboard.html` keeps its own inline `<style>` block (it does not `<link>` `theme.css` — `theme.css`'s own top comment documents this split, listing `dashboard.html` as one of the pages that keep their own inline styles, mirroring the shared variable names rather than sharing the file). Continue that convention: any new CSS (sidebar container, triage table, filter dropdowns) uses the same `--bg`/`--bg-elevated`/`--bg-elevated-2`/`--border`/`--border-soft`/`--text`/`--text-dim`/`--text-dimmer`/`--accent`/`--green`/`--amber`/`--red` (+ `-soft` variants) custom properties already defined in `dashboard.html`'s own `:root`/`html[data-theme="dark"]` blocks — do not hardcode light-theme-only colors, and do not introduce a second token system. The approved mockup is light theme; dark theme support must be preserved via these same variables, not dropped.

## 10. Responsiveness

Primary target 1920×1080 / 1440×900 (unchanged from today). At narrower widths, fall back to the existing single-column stacking pattern (`dashboard.html:388-390`'s `@media` block), extended to include the new `triage` area. No mobile optimization target. No page-level horizontal scroll.

## 11. Acceptance criteria

- Volume chart (6 lines + forecast + legend + presets + incident markers) and all KPI/forecast/sentiment computation logic are functionally unchanged.
- Donut chart and its HTML/JS/CSS are fully removed, no empty panel left behind.
- Sidebar shows exactly: Total Tickets, Bot Answered, Escalated to Human, Forecast Insight, in that order.
- Each of the 6 service cards shows a Sentiment row (label + % + 3-segment bar) at the bottom, with a single shared Positive/Neutral/Negative legend rendered once under the card grid.
- Live Activity feed is replaced by a full-width Live Triage Stream table with columns Time/Ticket ID/Service/Sentiment/Action/Ticket, one-line ellipsis-truncated ticket text, working Service/Sentiment/Action filters (no reset button), newest-first, capped at ~20 events, fixed-height with internal scroll.
- Rows are read-only (no click behavior).
- Everything renders correctly in both light and dark theme.
- No backend changes are required to ship this (the one sentiment-flattening enhancement in §6 is optional).
