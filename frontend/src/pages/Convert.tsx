import { useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  ApiError,
  subscribeConversion,
  type Conversion,
  type LlmBackend,
  type Skill,
  type SSEEvent,
  type TrainRunStatus,
} from "../lib/api";

/** Convert a scanned skill into a runnable LangGraph project via the companion
 *  skill-to-langgraph pipeline. Streams stage/log output live, then surfaces the
 *  6 validation checks + the produced dist/<skill>/ folder. */
const STAGE_ORDER = [
  "extract",
  "validate",
  "gen_evals",
  "pytest",
  "package",
  "parity",
  "improve",
];

const CHECK_LABELS: Record<string, string> = {
  schema_ok: "schema",
  codegen_ok: "codegen",
  compile_ok: "compile",
  nodes_match: "nodes",
  edges_cover: "edges",
  smoke_ok: "smoke",
};

export default function Convert() {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [skillId, setSkillId] = useState("");
  const [model, setModel] = useState("sonnet");
  const [runParity, setRunParity] = useState(false);
  const [backend, setBackend] = useState<LlmBackend>("claude_cli");
  const [offline, setOffline] = useState(false);

  const [convId, setConvId] = useState<string | null>(null);
  const [status, setStatus] = useState<TrainRunStatus | null>(null);
  const [activeStage, setActiveStage] = useState<string | null>(null);
  const [log, setLog] = useState<string[]>([]);
  const [result, setResult] = useState<Conversion | null>(null);
  const [launchError, setLaunchError] = useState<string | null>(null);
  const disposeRef = useRef<(() => void) | null>(null);
  const logEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    api
      .listSkills()
      .then((s) => {
        setSkills(s);
        setOffline(false);
        if (s.length && !skillId) setSkillId(s[0].id);
      })
      .catch((e) => {
        if (e instanceof ApiError) setOffline(true);
      });
    return () => disposeRef.current?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [log]);

  const running = status === "running";

  const onEvent = (e: SSEEvent) => {
    if (e.type === "stage") setActiveStage(e.stage);
    else if (e.type === "log")
      setLog((l) => [...l.slice(-400), `${e.stage ? `[${e.stage}] ` : ""}${e.line}`]);
    else if (e.type === "error")
      setLog((l) => [...l.slice(-400), `⚠ ${e.message}`]);
  };

  const start = async () => {
    if (!skillId) return;
    setLaunchError(null);
    setResult(null);
    setLog([]);
    setActiveStage(null);
    try {
      const created = await api.createConversion({
        skill_id: skillId,
        model,
        run_parity: runParity,
        llm_backend: backend,
      });
      setConvId(created.id);
      setStatus("running");
      disposeRef.current?.();
      disposeRef.current = subscribeConversion(created.id, {
        onEvent,
        onDone: (d) => {
          setStatus(d.status);
          setActiveStage(null);
          // Pull final artifacts after the stream closes.
          api.getConversion(created.id).then(setResult).catch(() => {});
        },
      });
    } catch (e) {
      const msg =
        e instanceof ApiError
          ? typeof e.body === "object" && e.body && "detail" in e.body
            ? String((e.body as { detail: unknown }).detail)
            : e.message
          : String(e);
      setLaunchError(msg);
    }
  };

  const cancel = () => {
    if (convId) api.cancelConversion(convId).catch(() => {});
  };

  const checks = result?.artifacts?.validation?.checks ?? null;
  const dist = result?.artifacts?.dist ?? null;
  const spec = result?.artifacts?.spec ?? null;

  const stageState = useMemo(() => {
    const stages = result?.stages ?? null;
    return STAGE_ORDER.map((name) => {
      const s = stages?.find((x) => x.name === name);
      if (s) return { name, state: s.skipped ? "skipped" : s.ok ? "ok" : "fail" };
      if (activeStage === name) return { name, state: "active" };
      return { name, state: "pending" };
    });
  }, [result, activeStage]);

  return (
    <div className="page">
      <header className="page-head">
        <h1>Convert to LangGraph</h1>
        <p className="muted">
          Turn a skill's SKILL.md into a runnable LangGraph project (graphspec →
          codegen → tests → portable dist/). Powered by the companion
          skill-to-langgraph converter.
        </p>
      </header>

      {offline && (
        <div className="banner bad">Backend offline — start it with ./run.sh</div>
      )}

      <section className="card" style={{ display: "grid", gap: 12, maxWidth: 640 }}>
        <label>
          <div className="muted">Skill</div>
          <select
            value={skillId}
            onChange={(e) => setSkillId(e.target.value)}
            disabled={running || !skills.length}
          >
            {skills.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} ({s.provider})
              </option>
            ))}
          </select>
        </label>

        <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
          <label>
            <div className="muted">Extract model</div>
            <select value={model} onChange={(e) => setModel(e.target.value)} disabled={running}>
              <option value="haiku">haiku</option>
              <option value="sonnet">sonnet</option>
              <option value="opus">opus</option>
            </select>
          </label>

          <label>
            <div className="muted">LLM backend</div>
            <select
              value={backend}
              onChange={(e) => setBackend(e.target.value as LlmBackend)}
              disabled={running}
            >
              <option value="claude_cli">claude -p (subscription)</option>
              <option value="api">API key (billed)</option>
            </select>
          </label>

          <label style={{ alignSelf: "end" }}>
            <input
              type="checkbox"
              checked={runParity}
              onChange={(e) => setRunParity(e.target.checked)}
              disabled={running}
            />{" "}
            Run live parity (costs LLM calls)
          </label>
        </div>

        <div style={{ display: "flex", gap: 8 }}>
          <button className="primary" onClick={start} disabled={running || !skillId}>
            {running ? "Converting…" : "Convert to LangGraph"}
          </button>
          {running && (
            <button onClick={cancel} className="ghost">
              Cancel
            </button>
          )}
          {status && !running && <span className={`pill ${status}`}>{status}</span>}
        </div>

        {launchError && <div className="banner bad">{launchError}</div>}
      </section>

      {(running || result) && (
        <section className="card" style={{ marginTop: 16 }}>
          <div className="stage-row" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {stageState.map((s) => (
              <span key={s.name} className={`stage-chip ${s.state}`}>
                {s.state === "ok" ? "✓ " : s.state === "fail" ? "✗ " : ""}
                {s.name}
              </span>
            ))}
          </div>

          <pre className="console" style={{ maxHeight: 280, overflow: "auto", marginTop: 12 }}>
            {log.join("\n")}
            <div ref={logEndRef} />
          </pre>
        </section>
      )}

      {result && checks && (
        <section className="card" style={{ marginTop: 16 }}>
          <h2>
            Result · {spec?.workflow_shape ?? "—"} · {spec?.node_count ?? 0} nodes
            {spec?.children?.length ? ` · subgraphs: ${spec.children.join(", ")}` : ""}
          </h2>
          <div className="check-row" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {Object.entries(checks).map(([k, v]) => (
              <span key={k} className={`check ${v ? "ok" : "fail"}`}>
                {v ? "✓" : "✗"} {CHECK_LABELS[k] ?? k}
              </span>
            ))}
          </div>

          {result.artifacts?.validation?.errors?.length ? (
            <ul className="errors">
              {result.artifacts.validation.errors.map((er, i) => (
                <li key={i}>{er}</li>
              ))}
            </ul>
          ) : null}

          {dist ? (
            <div style={{ marginTop: 12 }}>
              <div className="muted">Runnable deliverable</div>
              <code className="path">{dist.path}</code>
              <pre className="run-cmd" style={{ marginTop: 6 }}>
                {dist.run_command}
              </pre>
              <details style={{ marginTop: 8 }}>
                <summary>{dist.files.length} files</summary>
                <ul className="files">
                  {dist.files.map((f) => (
                    <li key={f}>{f}</li>
                  ))}
                </ul>
              </details>
            </div>
          ) : (
            <div className="muted" style={{ marginTop: 12 }}>
              No dist/ produced (conversion did not reach packaging).
            </div>
          )}

          {result.artifacts?.parity ? (
            <details style={{ marginTop: 12 }}>
              <summary>Live parity scores</summary>
              <pre>{JSON.stringify(result.artifacts.parity, null, 2)}</pre>
            </details>
          ) : null}
        </section>
      )}
    </div>
  );
}
