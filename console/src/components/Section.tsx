import { useState } from 'react';
import { BORDER, MUTED, TEXT_HEADING } from '../theme';

interface SectionProps {
  title: string;
  /** Shown next to the title while collapsed, so a closed section still reports its state. */
  summary?: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}

/**
 * A collapsible sidebar section.
 *
 * The sidebar had grown to one scroll of five always-open sections, and the Layers list at
 * the bottom — seventeen rows, mostly `planned` — pushed the venue counts off screen on a
 * laptop. Collapsing is preferred to tabs here because the sections are meant to be read
 * against each other: how many venues are drawn, and which layers are actually ready to
 * describe them, is one thought.
 *
 * `summary` matters more than it looks. A collapsed section that shows only a title hides
 * whether anything is switched on inside it, so the header carries the count or state that
 * would otherwise be lost.
 */
export function Section({ title, summary, defaultOpen = true, children }: SectionProps) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <section style={sectionStyle}>
      <button
        onClick={() => setOpen((v) => !v)}
        style={headerStyle}
        aria-expanded={open}
      >
        {/* A rotated caret rather than +/-, so the control reads the same as the disclosure
            triangles elsewhere in the UI. */}
        <span
          aria-hidden
          style={{
            display: 'inline-block',
            transform: open ? 'rotate(90deg)' : 'rotate(0deg)',
            transition: 'transform 120ms ease',
            fontSize: 9,
            color: MUTED,
          }}
        >
          ▶
        </span>
        <span style={{ flex: 1, textAlign: 'left' }}>{title}</span>
        {!open && summary && <span style={summaryStyle}>{summary}</span>}
      </button>
      {open && <div style={{ marginTop: 10 }}>{children}</div>}
    </section>
  );
}

const sectionStyle: React.CSSProperties = {
  marginBottom: 18,
  paddingBottom: 14,
  borderBottom: `1px solid ${BORDER}`,
};

const headerStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 8,
  width: '100%',
  padding: 0,
  background: 'none',
  border: 'none',
  cursor: 'pointer',
  color: TEXT_HEADING,
  fontSize: 11,
  textTransform: 'uppercase',
  letterSpacing: '0.09em',
  fontFamily: 'inherit',
};

const summaryStyle: React.CSSProperties = {
  color: MUTED,
  fontSize: 11,
  textTransform: 'none',
  letterSpacing: 0,
};
