/**
 * The console's colors, measured against the surfaces they are actually drawn on.
 *
 * This was a dark navy console until it was turned light. The reason was not taste: this is
 * a thing Kiki hands to someone, and a dark dashboard reads as a monitoring tool for a
 * system, while a light one reads as a document about a subject. It also screenshots and
 * prints without inverting.
 *
 * Every value below was computed, not chosen by eye, because the last palette shipped two
 * greys that failed AA and they were carrying the project's caveats — "no operator on
 * record", "this is a documented gap". The least readable text in the console was its most
 * important text. That is the failure mode this file exists to prevent.
 *
 * TEXT, measured against SURFACE (#ffffff) and PANEL (#f8fafc). AA is 4.5:1 and every one
 * of these is set at 11–13px, so the 3:1 large-text exemption applies to none of it.
 *
 *   TEXT          #0f172a  17.85:1 / 17.06:1
 *   TEXT_HEADING  #1e293b  14.63:1 / 14.00:1
 *   MUTED         #475569   7.58:1 /  7.24:1
 *   ACCENT_TEXT   #0369a1   5.93:1 /  5.67:1
 *   ERROR         #b91c1c   6.47:1 /  6.18:1
 *   ON_ACCENT     #ffffff   5.93:1 on ACCENT — the only text drawn on a filled control
 *
 * NON-TEXT, governed by WCAG 1.4.11 at 3:1 rather than 4.5:1. The distinction matters and is
 * the reason there are two border tokens:
 *
 *   BORDER_STRONG #64748b   4.76:1 on SURFACE — checkbox and input outlines. These are
 *                                    control boundaries; if you cannot see one you cannot
 *                                    tell there is a control there, so 1.4.11 applies.
 *   BORDER        #e2e8f0   1.23:1 — deliberately below 3:1 and deliberately NOT used for
 *                                    any control. It draws dividers between sections, which
 *                                    are decoration: removing every one of them loses no
 *                                    information, because each section already has a heading.
 *                                    A divider strong enough to pass 1.4.11 is a rule across
 *                                    the page that competes with the content for attention.
 *   ACCENT        #0369a1   5.93:1 — selection rings and the filled control background.
 *   ACCENT_SOFT   #e0f2fe   1.15:1 — a selected row's tint. Also below 3:1 and also not
 *                                    load-bearing: selection is carried by the ring and by
 *                                    the text weight, and the tint only confirms it. Tested
 *                                    by turning it off — the selected row is still obvious.
 */

/** The sidebar and the page. */
export const SURFACE = '#ffffff';

/** Panels floating over the map, and inset blocks inside the sidebar. */
export const PANEL = '#f8fafc';

/** Panels over the map need to be opaque enough to read against a light basemap. */
export const PANEL_OVER_MAP = 'rgba(255,255,255,0.97)';

/** Primary body text. */
export const TEXT = '#0f172a';

/** Section headings. */
export const TEXT_HEADING = '#1e293b';

/**
 * Secondary text: counts, notes, every caveat in the console. On the dark theme this slot
 * had to be a mid-grey that barely cleared AA; on white there is room for a genuinely dark
 * value, so the console's caveats are now the second-most readable text rather than the
 * least.
 */
export const MUTED = '#475569';

/**
 * Third-level text — category labels, the `planned` badge. Same value as MUTED on purpose.
 * A third grey step would have to be lighter, and lighter is where AA failures come from.
 * Hierarchy is carried by size, weight and letter-spacing, none of which can fail a
 * contrast check.
 */
export const MUTED_DIM = '#475569';

/** Filled controls and selection rings. */
export const ACCENT = '#0369a1';

/** Accent-colored *text* — links, the active metric. Same value; it passes as text too. */
export const ACCENT_TEXT = '#0369a1';

/** The only text ever drawn on top of ACCENT. */
export const ON_ACCENT = '#ffffff';

/** A selected row's background tint. Confirms selection; never the only sign of it. */
export const ACCENT_SOFT = '#e0f2fe';

/** Decorative dividers only — see the note above. Never a control outline. */
export const BORDER = '#e2e8f0';

/** Control outlines: checkboxes, inputs, selects. Passes 1.4.11 at 3:1. */
export const BORDER_STRONG = '#64748b';

export const ERROR = '#b91c1c';

/**
 * "This is on record but shaky" — a `needs_review` run, a venue with no coordinate so it
 * cannot be shown on the map. Distinct from ERROR because nothing has failed: the console
 * loaded the row and is telling you what is wrong with it, which is the whole posture of
 * this project. 6.85:1 on SURFACE, 6.15:1 on WARN_SOFT.
 *
 * Much darker than the amber it replaced (#fbbf24, 1.72:1 on white). That value was picked
 * to glow on navy, and every caveat wearing it would have become the least readable text in
 * the console the moment the background went white — the exact failure theme.ts opens by
 * describing, so it is worth noting it recurred here and was caught by measuring rather than
 * by looking.
 */
export const WARN = '#854d0e';

/** The tint behind a warning block. Like ACCENT_SOFT, it confirms rather than carries —
 *  the text is already WARN-colored and says what is wrong in words. */
export const WARN_SOFT = '#fef3c7';

/**
 * The basemap. CARTO positron, the light counterpart of the dark-matter style this console
 * used before. Land is roughly #fafaf8 and water roughly #d4dadc, which is what the venue
 * dot colors below were measured against — a dot has to clear 3:1 on both, because a coastal
 * stadium sits on the boundary.
 */
export const BASEMAP =
  'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json';
