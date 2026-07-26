import { useMemo, useState } from "react";
import type { SkillVersion } from "../lib/api";

/** Minimal LCS-free line diff (greedy) — good enough for skill markdown deltas. */
function lineDiff(a: string, b: string): { kind: "ctx" | "add" | "del"; text: string }[] {
  const al = a.split("\n");
  const bl = b.split("\n");
  const out: { kind: "ctx" | "add" | "del"; text: string }[] = [];
  let i = 0;
  let j = 0;
  while (i < al.length || j < bl.length) {
    if (i < al.length && j < bl.length && al[i] === bl[j]) {
      out.push({ kind: "ctx", text: al[i] });
      i++;
      j++;
    } else {
      // look ahead a small window to resync
      const aNext = bl.indexOf(al[i] ?? "\0", j);
      const bNext = al.indexOf(bl[j] ?? "\0", i);
      if (j < bl.length && (aNext === -1 || (bNext !== -1 && bNext < aNext))) {
        out.push({ kind: "add", text: bl[j] });
        j++;
      } else if (i < al.length) {
        out.push({ kind: "del", text: al[i] });
        i++;
      } else {
        out.push({ kind: "add", text: bl[j] });
        j++;
      }
    }
  }
  return out;
}

interface Props {
  versions: SkillVersion[];
  /** Optional best_skill.md text; if omitted, the is_best version is used. */
  bestSkill?: string | null;
}

/** Renders skill_vXXXX diffs between consecutive versions and surfaces the
 *  best_skill.md. Pick a left (base) and right (target) version to compare. */
export default function VersionDiff({ versions, bestSkill }: Props) {
  const sorted = useMemo(
    () => [...versions].sort((a, b) => a.step - b.step),
    [versions],
  );
  const bestVersion = sorted.find((v) => v.is_best);
  const [leftStep, setLeftStep] = useState<number>(sorted[0]?.step ?? 0);
  const [rightStep, setRightStep] = useState<number>(
    sorted[sorted.length - 1]?.step ?? 0,
  );

  const left = sorted.find((v) => v.step === leftStep);
  const right = sorted.find((v) => v.step === rightStep);
  const best = bestSkill ?? bestVersion?.md_text ?? null;

  const diff = useMemo(
    () =>
      left && right ? lineDiff(left.md_text, right.md_text) : [],
    [left, right],
  );

  const adds = diff.filter((d) => d.kind === "add").length;
  const dels = diff.filter((d) => d.kind === "del").length;

  return (
    <section className="card">
      <div className="card-head">
        <div className="card-title">
          Skill versions
          <small>{sorted.length} snapshots</small>
        </div>
        <div className="row gap-sm">
          <span className="chip chip-accept">+{adds}</span>
          <span className="chip chip-reject">−{dels}</span>
        </div>
      </div>

      {sorted.length === 0 ? (
        <div className="empty">No skill versions captured for this run yet.</div>
      ) : (
        <>
          <div className="card-pad row gap-sm row-wrap">
            <label className="row gap-sm" style={{ alignItems: "center" }}>
              <span className="field-label" style={{ margin: 0 }}>
                base
              </span>
              <select
                className="select"
                style={{ width: "auto" }}
                value={leftStep}
                onChange={(e) => setLeftStep(Number(e.target.value))}
              >
                {sorted.map((v) => (
                  <option key={v.step} value={v.step}>
                    skill_v{String(v.step).padStart(4, "0")}
                    {v.is_best ? " ★" : ""}
                  </option>
                ))}
              </select>
            </label>
            <span className="faint mono">→</span>
            <label className="row gap-sm" style={{ alignItems: "center" }}>
              <span className="field-label" style={{ margin: 0 }}>
                target
              </span>
              <select
                className="select"
                style={{ width: "auto" }}
                value={rightStep}
                onChange={(e) => setRightStep(Number(e.target.value))}
              >
                {sorted.map((v) => (
                  <option key={v.step} value={v.step}>
                    skill_v{String(v.step).padStart(4, "0")}
                    {v.is_best ? " ★" : ""}
                  </option>
                ))}
              </select>
            </label>
            {bestVersion && (
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => {
                  setLeftStep(sorted[0].step);
                  setRightStep(bestVersion.step);
                }}
              >
                ★ diff to best
              </button>
            )}
          </div>

          <div className="card-pad" style={{ paddingTop: 0 }}>
            <div className="diff" role="region" aria-label="version diff">
              {diff.map((d, i) => (
                <span key={i} className={`diff-line diff-${d.kind}`}>
                  {d.text || " "}
                </span>
              ))}
            </div>
          </div>

          {best && (
            <details className="card-pad" style={{ paddingTop: 0 }}>
              <summary
                className="field-label"
                style={{ cursor: "pointer", marginBottom: 8 }}
              >
                best_skill.md ★
              </summary>
              <pre className="console" style={{ height: "auto", maxHeight: 420 }}>
                {best}
              </pre>
            </details>
          )}
        </>
      )}
    </section>
  );
}
