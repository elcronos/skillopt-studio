import { useEffect, useRef } from "react";
import type { ProviderName } from "../lib/api";

export type SortKey = "name-asc" | "name-desc" | "provider" | "path";

export const SORT_OPTIONS: { key: SortKey; label: string }[] = [
  { key: "name-asc", label: "Name A→Z" },
  { key: "name-desc", label: "Name Z→A" },
  { key: "provider", label: "Provider" },
  { key: "path", label: "Path" },
];

/** The provider filter universe. "all" is a synthetic bucket. */
export type ProviderFilter = "all" | ProviderName;

const PROVIDER_CHIP: Record<string, string> = {
  claude: "chip-signal",
  openai: "chip-accept",
  codex: "chip-cyan",
  cwd: "chip",
};

interface Props {
  query: string;
  onQuery: (q: string) => void;
  provider: ProviderFilter;
  onProvider: (p: ProviderFilter) => void;
  sort: SortKey;
  onSort: (s: SortKey) => void;
  /** Live per-provider counts (over the unfiltered set), plus the total. */
  counts: Record<ProviderFilter, number>;
  total: number;
  matched: number;
}

/** Search + provider-filter chips + sort control for the Discovered skills list.
 *  Press "/" anywhere (outside an input) to focus the search box. */
export default function SkillToolbar({
  query,
  onQuery,
  provider,
  onProvider,
  sort,
  onSort,
  counts,
  total,
  matched,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);

  // "/" focuses search (the classic command-palette affordance).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "/" || e.metaKey || e.ctrlKey || e.altKey) return;
      const t = e.target as HTMLElement | null;
      const tag = t?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || t?.isContentEditable) return;
      e.preventDefault();
      inputRef.current?.focus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const providers: ProviderFilter[] = ["all", "claude", "codex", "openai", "cwd"];

  return (
    <div className="skill-toolbar">
      <div className="skill-search">
        <span className="skill-search-icon mono" aria-hidden="true">
          ⌕
        </span>
        <input
          ref={inputRef}
          className="input skill-search-input"
          type="search"
          placeholder="Filter by name or path…"
          value={query}
          onChange={(e) => onQuery(e.target.value)}
          aria-label="Filter skills by name or path"
        />
        {query ? (
          <button
            type="button"
            className="skill-search-clear"
            onClick={() => onQuery("")}
            aria-label="Clear search"
            title="Clear"
          >
            ×
          </button>
        ) : (
          <kbd className="skill-search-kbd" aria-hidden="true">
            /
          </kbd>
        )}
      </div>

      <div className="skill-toolbar-row">
        <div className="row row-wrap gap-sm" role="group" aria-label="Filter by provider">
          {providers.map((p) => {
            const chipClass = p === "all" ? "chip" : PROVIDER_CHIP[p] ?? "chip";
            const isOn = provider === p;
            const n = counts[p] ?? 0;
            return (
              <button
                key={p}
                type="button"
                className={`chip skill-filter-chip ${chipClass} ${
                  isOn ? "is-on" : ""
                }`}
                onClick={() => onProvider(p)}
                aria-pressed={isOn}
                disabled={p !== "all" && n === 0}
                title={`${p} (${n})`}
              >
                {p} <span className="faint">{n}</span>
              </button>
            );
          })}
        </div>

        <label className="skill-sort">
          <span className="field-label skill-sort-label">sort</span>
          <select
            className="select skill-sort-select"
            value={sort}
            onChange={(e) => onSort(e.target.value as SortKey)}
            aria-label="Sort skills"
          >
            {SORT_OPTIONS.map((o) => (
              <option key={o.key} value={o.key}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="skill-match-count mono" aria-live="polite">
        {matched} of {total} matched
      </div>
    </div>
  );
}
