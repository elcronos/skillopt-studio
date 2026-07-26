import { useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { api, type HealthInfo } from "./lib/api";
import Skills from "./pages/Skills";
import Train from "./pages/Train";
import RunDetail from "./pages/RunDetail";
import Convert from "./pages/Convert";

function HealthIndicator() {
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [reachable, setReachable] = useState<boolean | null>(null);

  useEffect(() => {
    let alive = true;
    const ping = () =>
      api
        .health()
        .then((h) => {
          if (!alive) return;
          setHealth(h);
          setReachable(true);
        })
        .catch(() => {
          if (!alive) return;
          setReachable(false);
        });
    ping();
    const t = setInterval(ping, 8000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  const led =
    reachable === null ? "" : reachable && health?.status ? "ok" : "bad";
  const label =
    reachable === null
      ? "connecting…"
      : reachable
        ? `backend ${health?.status ?? "up"}`
        : "backend offline";

  return (
    <div className="sidebar-foot">
      <div>:8000 · api</div>
      <div className="health-row">
        <span className={`health-led ${led}`} />
        <span>{label}</span>
      </div>
      {health?.python_version && (
        <div className="health-row" style={{ marginTop: 4 }}>
          <span>py {health.python_version}</span>
        </div>
      )}
    </div>
  );
}

export default function App() {
  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">∿</div>
          <div>
            <div className="brand-name">SkillOpt</div>
            <div className="brand-sub">Studio</div>
          </div>
        </div>

        <NavLink to="/skills" className="nav-link">
          <span className="nav-dot" /> Skills
        </NavLink>
        <NavLink to="/train" className="nav-link">
          <span className="nav-dot" /> Train
        </NavLink>
        <NavLink to="/runs" className="nav-link">
          <span className="nav-dot" /> Runs
        </NavLink>
        <NavLink to="/convert" className="nav-link">
          <span className="nav-dot" /> Convert
        </NavLink>

        <HealthIndicator />
      </aside>

      <main className="main">
        <Routes>
          <Route path="/" element={<Navigate to="/skills" replace />} />
          <Route path="/skills" element={<Skills />} />
          <Route path="/train" element={<Train />} />
          <Route path="/runs" element={<Train />} />
          <Route path="/runs/:runId" element={<RunDetail />} />
          <Route path="/convert" element={<Convert />} />
          <Route path="*" element={<Navigate to="/skills" replace />} />
        </Routes>
      </main>
    </div>
  );
}
