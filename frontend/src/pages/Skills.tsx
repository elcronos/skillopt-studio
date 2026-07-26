import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError, type Skill } from "../lib/api";
import SkillList from "../components/SkillList";
import StructureGraphPanel from "../components/StructureGraphPanel";
import SkillToolbar, {
  type ProviderFilter,
  type SortKey,
} from "../components/SkillToolbar";

export default function Skills() {
  const nav = useNavigate();
  const [skills, setSkills] = useState<Skill[]>([]);
  const [selected, setSelected] = useState<Skill | null>(null);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [offline, setOffline] = useState(false);

  // Toolbar state: search query, provider filter, sort key.
  const [query, setQuery] = useState("");
  const [provider, setProvider] = useState<ProviderFilter>("all");
  const [sort, setSort] = useState<SortKey>("name-asc");

  const load = () => {
    setLoading(true);
    api
      .listSkills()
      .then((s) => {
        setSkills(s);
        setOffline(false);
        if (s.length && !selected) hydrate(s[0]);
      })
      .catch((e) => {
        if (e instanceof ApiError) setOffline(true);
        setSkills([]);
      })
      .finally(() => setLoading(false));
  };

  // Fetch full body for the structure panel (list may be lightweight).
  const hydrate = (s: Skill) => {
    setSelected(s);
    if (!s.body) {
      api
        .getSkill(s.id)
        .then((full) => setSelected(full))
        .catch(() => {
          /* keep lightweight version */
        });
    }
  };

  useEffect(load, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Live per-provider counts over the full discovered set (for filter chips).
  const counts = useMemo(() => {
    const base: Record<ProviderFilter, number> = {
      all: skills.length,
      claude: 0,
      codex: 0,
      openai: 0,
      cwd: 0,
    };
    for (const s of skills) {
      if (s.provider in base) base[s.provider] += 1;
    }
    return base;
  }, [skills]);

  // Filter (provider + case-insensitive name/path substring) then sort.
  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const out = skills.filter((s) => {
      if (provider !== "all" && s.provider !== provider) return false;
      if (!q) return true;
      return (
        s.name.toLowerCase().includes(q) ||
        s.source_path.toLowerCase().includes(q)
      );
    });
    const byName = (a: Skill, b: Skill) =>
      a.name.localeCompare(b.name, undefined, { sensitivity: "base" });
    switch (sort) {
      case "name-asc":
        out.sort(byName);
        break;
      case "name-desc":
        out.sort((a, b) => byName(b, a));
        break;
      case "provider":
        out.sort((a, b) => a.provider.localeCompare(b.provider) || byName(a, b));
        break;
      case "path":
        out.sort(
          (a, b) => a.source_path.localeCompare(b.source_path) || byName(a, b),
        );
        break;
    }
    return out;
  }, [skills, query, provider, sort]);

  const isFiltering = query.trim() !== "" || provider !== "all";

  // Discovery is a plain GET /api/skills — there is no POST scan endpoint.
  const scan = () => {
    setScanning(true);
    api
      .listSkills()
      .then((s) => {
        setSkills(s);
        setOffline(false);
        if (s.length) hydrate(s[0]);
      })
      .catch(() => setOffline(true))
      .finally(() => setScanning(false));
  };

  return (
    <div className="fade-up">
      <div className="page-head">
        <div>
          <div className="eyebrow">provider index</div>
          <h1 className="page-title">Skills</h1>
          <p className="page-sub">
            Discover skills across claude / codex / openai / cwd providers,
            inspect their structure graph, then send one to the optimizer.
          </p>
        </div>
        <button
          className="btn btn-primary"
          onClick={scan}
          disabled={scanning}
          type="button"
        >
          {scanning ? <span className="spin" /> : "⟳ refresh skills"}
        </button>
      </div>

      {offline && (
        <div className="banner banner-info" style={{ marginBottom: 20 }}>
          <span className="banner-icon">ℹ</span>
          <div>
            Skills API unavailable — the backend (port 8000) may still be coming
            online. Retry the scan once it is up.
          </div>
        </div>
      )}

      <div
        className="grid"
        style={{ gridTemplateColumns: "minmax(320px, 0.85fr) 1.6fr" }}
      >
        <section className="card">
          <div className="card-head">
            <div className="card-title">
              Discovered skills
              <small>
                {isFiltering
                  ? `${visible.length} of ${skills.length} indexed`
                  : `${skills.length} indexed`}
              </small>
            </div>
          </div>
          {!loading && skills.length > 0 && (
            <SkillToolbar
              query={query}
              onQuery={setQuery}
              provider={provider}
              onProvider={setProvider}
              sort={sort}
              onSort={setSort}
              counts={counts}
              total={skills.length}
              matched={visible.length}
            />
          )}
          <SkillList
            skills={visible}
            selectedId={selected?.id}
            loading={loading}
            onSelect={hydrate}
            filtered={isFiltering}
            query={query}
          />
          {selected && (
            <div
              className="card-pad row between"
              style={{ borderTop: "1px solid var(--border)" }}
            >
              <span className="faint mono">{selected.id}</span>
              <button
                className="btn btn-sm btn-primary"
                onClick={() =>
                  nav(`/train?skill=${encodeURIComponent(selected.id)}`)
                }
              >
                optimize this skill →
              </button>
            </div>
          )}
        </section>

        <StructureGraphPanel skill={selected} />
      </div>
    </div>
  );
}
