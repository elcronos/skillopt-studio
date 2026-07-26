import { useState } from "react";
import { api, type ModelConfig } from "../lib/api";

const BACKENDS = [
  "openai_chat",
  "openai_compatible",
  "claude_chat",
  "qwen_chat",
  "minimax_chat",
];

interface Props {
  value: ModelConfig;
  onChange: (m: ModelConfig) => void;
}

/** Backend + optimizer/target model selection, endpoint, and write-only keys.
 *  Keys are persisted by creating a named model (POST /api/models) with the
 *  keys in the create body — there is no separate key endpoint. The key fields
 *  clear after save and the form shows a "stored" state. */
export default function ModelConfigForm({ value, onChange }: Props) {
  const [name, setName] = useState("");
  const [optKeyDraft, setOptKeyDraft] = useState("");
  const [targetKeyDraft, setTargetKeyDraft] = useState("");
  const [keyState, setKeyState] = useState<"idle" | "saving" | "stored" | "error">(
    "idle",
  );
  const patch = (p: Partial<ModelConfig>) => onChange({ ...value, ...p });

  const saveModel = async () => {
    if (!name || (!optKeyDraft && !targetKeyDraft)) return;
    setKeyState("saving");
    try {
      await api.saveModel({
        name,
        model: value,
        ...(optKeyDraft ? { optimizer_api_key: optKeyDraft } : {}),
        ...(targetKeyDraft ? { target_api_key: targetKeyDraft } : {}),
      });
      setOptKeyDraft("");
      setTargetKeyDraft("");
      setKeyState("stored");
    } catch {
      setKeyState("error");
    }
  };

  return (
    <section className="card">
      <div className="card-head">
        <div className="card-title">
          Model & backend
          <small>optimizer drives edits · target runs rollouts</small>
        </div>
        <span className="chip mono">{value.backend}</span>
      </div>

      <div className="card-pad">
        <label className="field">
          <span className="field-label">Backend</span>
          <select
            className="select"
            value={value.backend}
            onChange={(e) => patch({ backend: e.target.value })}
          >
            {BACKENDS.map((b) => (
              <option key={b} value={b}>
                {b}
              </option>
            ))}
          </select>
        </label>

        <div className="grid grid-2">
          <label className="field">
            <span className="field-label">Optimizer model</span>
            <input
              className="input"
              value={value.optimizer_model}
              onChange={(e) => patch({ optimizer_model: e.target.value })}
            />
          </label>
          <label className="field">
            <span className="field-label">Target model</span>
            <input
              className="input"
              value={value.target_model}
              onChange={(e) => patch({ target_model: e.target.value })}
            />
          </label>
        </div>

        <div className="grid grid-2">
          <label className="field">
            <span className="field-label">Optimizer backend (optional)</span>
            <input
              className="input"
              value={value.optimizer_backend ?? ""}
              placeholder={`inherit · ${value.backend}`}
              onChange={(e) =>
                patch({ optimizer_backend: e.target.value || null })
              }
            />
          </label>
          <label className="field">
            <span className="field-label">Target backend (optional)</span>
            <input
              className="input"
              value={value.target_backend ?? ""}
              placeholder={`inherit · ${value.backend}`}
              onChange={(e) =>
                patch({ target_backend: e.target.value || null })
              }
            />
          </label>
        </div>

        <div className="grid grid-2">
          <label className="field">
            <span className="field-label">Endpoint (optional)</span>
            <input
              className="input"
              value={value.endpoint ?? ""}
              placeholder="https://…openai.azure.com"
              onChange={(e) => patch({ endpoint: e.target.value || null })}
            />
          </label>
          <label className="field">
            <span className="field-label">API version (optional)</span>
            <input
              className="input"
              value={value.api_version ?? ""}
              placeholder="2024-08-01-preview"
              onChange={(e) => patch({ api_version: e.target.value || null })}
            />
          </label>
        </div>

        <label className="field">
          <span className="field-label">Reasoning effort</span>
          <select
            className="select"
            value={value.reasoning_effort}
            onChange={(e) => patch({ reasoning_effort: e.target.value })}
          >
            {["minimal", "low", "medium", "high"].map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </label>

        {/* Write-only keys — persisted by creating a named model. */}
        <div
          style={{
            borderTop: "1px solid var(--border)",
            paddingTop: 16,
            marginTop: 4,
          }}
        >
          <span className="field-label">
            Save as named model + API keys — write-only
          </span>
          <label className="field">
            <span className="field-label">Model name</span>
            <input
              className="input"
              value={name}
              placeholder="e.g. azure-gpt5"
              onChange={(e) => {
                setName(e.target.value);
                setKeyState("idle");
              }}
            />
          </label>
          <div className="grid grid-2">
            <label className="field">
              <span className="field-label">Optimizer API key</span>
              <input
                className="input"
                type="password"
                value={optKeyDraft}
                autoComplete="off"
                placeholder="never read back"
                onChange={(e) => {
                  setOptKeyDraft(e.target.value);
                  setKeyState("idle");
                }}
              />
            </label>
            <label className="field">
              <span className="field-label">Target API key (optional)</span>
              <input
                className="input"
                type="password"
                value={targetKeyDraft}
                autoComplete="off"
                placeholder="defaults to optimizer key"
                onChange={(e) => {
                  setTargetKeyDraft(e.target.value);
                  setKeyState("idle");
                }}
              />
            </label>
          </div>
          <button
            className="btn btn-primary btn-sm"
            type="button"
            onClick={saveModel}
            disabled={
              !name ||
              (!optKeyDraft && !targetKeyDraft) ||
              keyState === "saving"
            }
          >
            {keyState === "saving" ? <span className="spin" /> : "store model"}
          </button>
          {keyState === "stored" && (
            <span className="field-hint" style={{ color: "var(--accept)" }}>
              ✓ model saved — keys injected to the train subprocess via env,
              never argv or logs.
            </span>
          )}
          {keyState === "error" && (
            <span className="field-hint" style={{ color: "var(--danger)" }}>
              Could not save model (endpoint offline).
            </span>
          )}
        </div>
      </div>
    </section>
  );
}
