import { useEffect, useRef } from "react";

export interface ConsoleLine {
  text: string;
  kind?: "log" | "stage" | "err" | "muted";
}

interface Props {
  lines: ConsoleLine[];
  /** Set when an error event arrived; shows a failure indicator in the header. */
  failure?: { message: string; recoverable: boolean } | null;
  autoScroll?: boolean;
}

/** Streamed stdout with a failure indicator surfaced on the `error` SSE event. */
export default function RunConsole({
  lines,
  failure,
  autoScroll = true,
}: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (autoScroll && ref.current) {
      ref.current.scrollTop = ref.current.scrollHeight;
    }
  }, [lines, autoScroll]);

  return (
    <section className="card">
      <div className="card-head">
        <div className="card-title">
          Console
          <small>subprocess stdout · PYTHONUNBUFFERED</small>
        </div>
        {failure ? (
          <span
            className={`status-pill ${
              failure.recoverable ? "status-cancelled" : "status-failed"
            }`}
          >
            {failure.recoverable ? "recoverable error" : "failed"}
          </span>
        ) : (
          <span className="chip mono">{lines.length} lines</span>
        )}
      </div>

      {failure && !failure.recoverable && (
        <div className="card-pad" style={{ paddingBottom: 0 }}>
          <div className="banner banner-danger" role="alert">
            <span className="banner-icon">✕</span>
            <div>{failure.message}</div>
          </div>
        </div>
      )}

      <div className="card-pad">
        <div className="console" ref={ref} data-testid="run-console">
          {lines.length === 0 ? (
            <span className="console-line muted">
              waiting for output… stdout streams here line-by-line.
            </span>
          ) : (
            lines.map((l, i) => (
              <span key={i} className={`console-line ${l.kind ?? ""}`}>
                {l.text}
              </span>
            ))
          )}
        </div>
      </div>
    </section>
  );
}
