import type { Skill } from "../lib/api";

const PROVIDER_CHIP: Record<string, string> = {
  claude: "chip-signal",
  openai: "chip-accept",
  codex: "chip-cyan",
  cwd: "chip",
};

interface Props {
  skills: Skill[];
  selectedId?: string | null;
  onSelect?: (s: Skill) => void;
  loading?: boolean;
  /** When true, an empty list is treated as "no matches for the active filter"
   *  rather than "nothing discovered yet". */
  filtered?: boolean;
  /** Active search query, surfaced in the no-match empty state. */
  query?: string;
}

/** Provider + source_path provenance list. Each row shows the skill name,
 *  the discovering provider as a colored chip, and the absolute source path. */
export default function SkillList({
  skills,
  selectedId,
  onSelect,
  loading,
  filtered,
  query,
}: Props) {
  if (loading) {
    return (
      <div className="empty">
        <span className="spin" /> &nbsp; scanning providers…
      </div>
    );
  }
  if (skills.length === 0) {
    if (filtered) {
      return (
        <div className="empty">
          <div className="big">⌀</div>
          {query
            ? <>no skills match “<span className="mono">{query}</span>”</>
            : "no skills match the active filter"}
        </div>
      );
    }
    return (
      <div className="empty">
        <div className="big">⌀</div>
        No skills discovered yet. Run a scan to index claude / codex / openai /
        cwd providers.
      </div>
    );
  }

  return (
    <div role="list">
      {skills.map((s) => (
        <button
          key={s.id}
          role="listitem"
          type="button"
          className={`skill-row ${selectedId === s.id ? "selected" : ""}`}
          style={{
            width: "100%",
            textAlign: "left",
            background: "transparent",
            border: "none",
            borderBottom: "1px solid var(--border)",
          }}
          onClick={() => onSelect?.(s)}
          aria-pressed={selectedId === s.id}
        >
          <span className={`chip ${PROVIDER_CHIP[s.provider] ?? "chip"}`}>
            {s.provider}
          </span>
          <span style={{ minWidth: 0, flex: 1 }}>
            <span className="skill-name">{s.name}</span>
            <span className="skill-path" title={s.source_path}>
              {s.source_path}
            </span>
          </span>
          <span className="chip mono">{s.id}</span>
        </button>
      ))}
    </div>
  );
}
