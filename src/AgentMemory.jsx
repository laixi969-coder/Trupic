import React, { useEffect, useState } from "react";
import { api, Modal } from "./ui.jsx";

export default function AgentMemory({
  project,
  projectName,
  assets,
  weeks,
  onWeeks,
  onClose,
}) {
  const [rows, setRows] = useState([]),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const [name, setName] = useState(""),
    [value, setValue] = useState(""),
    [scope, setScope] = useState(""),
    [kind, setKind] = useState("fact"),
    [editing, setEditing] = useState(null);
  const path = "/agent/memory";
  async function load() {
    setRows((await api(path + (project ? "?project=" + project : ""))).entries);
  }
  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, [project]);
  async function perform(fn) {
    setBusy(true);
    setError("");
    try {
      await fn();
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  function reset() {
    setEditing(null);
    setValue("");
    setName("");
    setKind("fact");
  }
  return (
    <Modal title="助理记忆" onClose={onClose}>
      <div className="agent-memory">
        <a href="#profile" onClick={onClose}>
          编辑店铺资料与行业
        </a>
        {rows.map((r) => (
          <div className="agent-memory-row" key={r.id}>
            <small>
              {r.project ? projectName : "所有对话"} ·{" "}
              {r.active ? "使用中" : "已停用"}
            </small>
            <strong>{r.name}</strong>
            <p>
              {r.kind === "asset"
                ? assets.find((a) => a.id === r.value)?.name || "素材已移除"
                : r.value}
            </p>
            <div className="agent-links">
              <button
                disabled={busy}
                onClick={() => {
                  setEditing(r);
                  setName(r.name);
                  setValue(r.value);
                  setKind(r.kind);
                  setScope(r.project);
                }}
              >
                纠正
              </button>
              <button
                disabled={busy}
                onClick={() =>
                  perform(() =>
                    api(path + "/" + r.id, "PATCH", {
                      version: r.version,
                      active: !r.active,
                    }),
                  )
                }
              >
                {r.active ? "停用" : "启用"}
              </button>
              <button
                disabled={busy}
                onClick={() =>
                  perform(async () => {
                    await api(path + "/" + r.id, "DELETE", {
                      version: r.version,
                    });
                    if (editing?.id === r.id) reset();
                  })
                }
              >
                删除
              </button>
            </div>
          </div>
        ))}
        <form
          className="agent-memory-form"
          onSubmit={(e) => {
            e.preventDefault();
            perform(async () => {
              if (editing)
                await api(path + "/" + editing.id, "PATCH", {
                  version: editing.version,
                  value,
                });
              else
                await api(path, "POST", { name, value, kind, project: scope });
              reset();
            });
          }}
        >
          <h3>{editing ? "纠正记忆" : "添加已确认的记忆"}</h3>
          <div>
            <select
              disabled={!!editing}
              aria-label="记忆范围"
              value={scope}
              onChange={(e) => setScope(e.target.value)}
            >
              <option value="">所有对话</option>
              {project && <option value={project}>{projectName}</option>}
            </select>
            <select
              aria-label="记忆类型"
              disabled={!!editing}
              value={kind}
              onChange={(e) => {
                setKind(e.target.value);
                setValue("");
              }}
            >
              <option value="fact">经营事实</option>
              <option value="preference">创作偏好</option>
              <option value="asset">共享素材</option>
            </select>
          </div>
          <input
            required
            disabled={!!editing}
            aria-label="记忆名称"
            placeholder="名称，例如门店招牌"
            maxLength={60}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          {kind === "asset" ? (
            <select
              aria-label="共享素材"
              required
              value={value}
              onChange={(e) => setValue(e.target.value)}
            >
              <option value="">选择素材</option>
              {assets.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          ) : (
            <textarea
              required
              aria-label="记忆内容"
              placeholder="希望助理记住什么？"
              maxLength={240}
              value={value}
              onChange={(e) => setValue(e.target.value)}
            />
          )}
          <div>
            <button className="primary" disabled={busy}>
              保存记忆
            </button>{" "}
            {editing && (
              <button type="button" className="textbtn" onClick={reset}>
                取消修改
              </button>
            )}
          </div>
        </form>
        <label>
          营销主题推荐{" "}
          <select
            value={weeks}
            disabled={busy}
            onChange={(e) =>
              perform(async () => {
                const w = Number(e.target.value);
                await api("/agent/preferences", "POST", { weeks: w });
                onWeeks(w);
              })
            }
          >
            <option value={1}>每周</option>
            <option value={2}>每两周</option>
            <option value={3}>每三周</option>
            <option value={4}>每四周</option>
            <option value={0}>暂停</option>
          </select>
        </label>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
      </div>
    </Modal>
  );
}
