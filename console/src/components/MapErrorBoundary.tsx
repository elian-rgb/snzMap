import { Component, type ErrorInfo, type ReactNode } from 'react';
import { BORDER, MUTED, PANEL, TEXT_HEADING, WARN, WARN_SOFT } from '../theme';

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * Keeps a failed map from taking the console down with it.
 *
 * This exists because of a measured failure, not a hypothetical one. `MapView` constructs
 * `maplibregl.Map` inside an effect, and on a browser that cannot give it a WebGL2 context
 * that constructor throws `GPUInitializationError`. React propagates a throw from an effect
 * the same way it propagates one from render: with nothing to catch it, the whole tree
 * unmounts. The observed result was `document.body.innerText.length === 0` — a white page,
 * no message, no sidebar.
 *
 * That is the worst outcome this console can produce. The map is one of two halves; the other
 * half is the sidebar, and the sidebar is where the evidence is — the venue counts, the
 * rejection ratios, the wage-and-hour figures, and every caveat attached to them. All of it
 * renders without a GPU. Losing the map should cost the map.
 *
 * The fallback names the cause rather than apologising, on the same principle as the rest of
 * the console: an absence with a reason on it can be acted on, and a blank rectangle cannot.
 */
export class MapErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Kept, because the fallback deliberately does not print a stack at the reader and this
    // is then the only place the actual failure survives.
    console.error('Map failed to initialise:', error, info.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    // MapLibre's own message for a missing GPU context names WebGL2, so the specific cause
    // can be told apart from any other map failure and given the one sentence that actually
    // helps. Anything else falls through to the general case rather than being guessed at.
    const noWebgl = /webgl/i.test(error.message);

    return (
      <div style={wrapStyle}>
        <div style={cardStyle}>
          <h2 style={headingStyle}>The map could not start</h2>
          <p style={bodyStyle}>
            {noWebgl ? (
              <>
                This browser did not provide a WebGL2 context, which the map needs to draw.
                That is usually hardware acceleration being switched off, a remote or virtual
                desktop, or a locked-down browser profile — not a problem with this page.
              </>
            ) : (
              <>The map failed to initialise, and the reason is in the browser console.</>
            )}
          </p>
          <p style={bodyStyle}>
            <strong style={{ color: TEXT_HEADING }}>The sidebar still works.</strong> Every
            figure in it — the venue counts, the federal and wage-and-hour totals, the
            neighbourhood measures and the caveats on all of them — is computed from the same
            data and does not need the map.
          </p>
          {/* Only in the general case. When the cause is known the paragraph above already
              says it in words, and repeating the raw string verbatim underneath reads as a
              second, different problem. */}
          {!noWebgl && (
            <p style={{ ...bodyStyle, color: MUTED, marginBottom: 0 }}>{error.message}</p>
          )}
        </div>
      </div>
    );
  }
}

const wrapStyle: React.CSSProperties = {
  position: 'absolute',
  inset: 0,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  padding: 24,
  background: PANEL,
};

const cardStyle: React.CSSProperties = {
  maxWidth: 460,
  padding: '18px 20px',
  background: WARN_SOFT,
  border: `1px solid ${BORDER}`,
  borderRadius: 10,
};

const headingStyle: React.CSSProperties = {
  margin: '0 0 8px',
  fontSize: 15,
  color: WARN,
};

const bodyStyle: React.CSSProperties = {
  margin: '0 0 10px',
  fontSize: 12,
  lineHeight: 1.6,
  color: WARN,
};
