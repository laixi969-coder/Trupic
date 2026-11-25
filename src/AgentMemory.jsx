import React, { useEffect, useState } from "react";
import { Check, Layers, Sparkles, X } from "lucide-react";
import { api, Modal } from "./ui.jsx";

const statusLabel = {
  confirmed: "使用中",
  candidate: "待确认",
  expired: "已过期",
  revoked: "已撤销",
};

const kindLabel = {
  fact: "经营事实",
  preference: "创作偏好",
  asset: "共享素材",
};

export default function AgentMemory({
  conversationId,
  project,
  projectName,
  assets,
  weeks,
  onWeeks,
  onChanged,
  onClose,
}) {
  const [rows, setRows] = useState([]),
    [contextPacket, setContextPacket] = useState(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const [name, setName] = useState(""),
    [value, setValue] = useState(""),
    [scope, setScope] = useState(""),
    [kind, setKind] = useState("fact"),
    [expiresAt, setExpiresAt] = useState(""),
    [editing, setEditing] = useState(null);
  const path = "/agent/memory";

  async function load() {
    const res = await api(path + (project ? "?project=" + project : ""));
    setRows(res.entries || []);
    if (conversationId) {
      try {
        setContextPacket(
          await api("/agent/conversations/" + conversationId + "/context"),
        );
      } catch {
        setContextPacket(null);
      }
    }
  }
  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, [project, conversationId]);

  async function perform(fn) {
    setBusy(true);
    setError("");
    try {
      await fn();
      await load();
      onChanged?.();
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
    setExpiresAt("");
  }

  const candidates = rows.filter((r) => r.status === "candidate");
  const projectRows = rows.filter((r) => r.status !== "candidate" && r.project);
  const merchantRows = rows.filter(
    (r) => r.status !== "candidate" && !r.project,
  );

  const renderRow = (r) => (
    <div className="agent-memory-row" key={r.id}>
      <div className="agent-memory-head">
        <strong>{r.name}</strong>
        <small>
          {kindLabel[r.kind] || r.kind} ·{" "}
          {r.status === "expired"
            ? "已过期"
            : r.active
              ? statusLabel[r.status] || "使用中"
              : "已停用"}
          {r.expires_at ? ` · 有效期至 ${r.expires_at}` : ""}
          {r.hit_count > 0 ? ` · 已参考 ${r.hit_count} 次` : ""}
        </small>
      </div>
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
            setExpiresAt(r.expires_at || "");
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
  );

  return (
    <Modal title="助理记忆" onClose={onClose}>
      <div className="agent-memory">
        <div className="agent-memory-top">
          <a href="#profile" onClick={onClose}>
            编辑店铺资料与行业 ›
          </a>
          <small>可直接对助理说「记住：…」或「忘掉…」</small>
        </div>

        {candidates.length > 0 && (
          <div className="agent-memory-group candidate">
            <h3>
              <Sparkles size={14} /> 待确认的新记忆
            </h3>
            {candidates.map((r) => (
              <div className="agent-memory-row" key={r.id}>
                <strong>{r.name}</strong>
                <p>{r.value}</p>
                <div className="agent-links">
                  <button
                    className="agent-chip-primary"
                    disabled={busy}
                    onClick={() =>
                      perform(() =>
                        api(path + "/" + r.id + "/confirm", "POST", {
                          version: r.version,
                        }),
                      )
                    }
                  >
                    <Check size={14} />
                    确认记住
                  </button>
                  <button
                    disabled={busy}
                    onClick={() =>
                      perform(() =>
                        api(path + "/" + r.id + "/dismiss", "POST", {
                          version: r.version,
                        }),
                      )
                    }
                  >
                    <X size={14} />
                    忽略
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        {project && (
          <div className="agent-memory-group">
            <h3>当前项目记忆 · {projectName}</h3>
            {projectRows.length === 0 && (
              <small>这个项目还没有专属记忆（仅本项目内共享）。</small>
            )}
            {projectRows.map(renderRow)}
          </div>
        )}

        <div className="agent-memory-group">
          <h3>店铺长期记忆（所有对话共享）</h3>
          {merchantRows.length === 0 && (
            <small>还没有已确认的长期记忆。</small>
          )}
          {merchantRows.map(renderRow)}
        </div>

        {contextPacket?.layers?.ephemeral?.compacted && (
          <details className="agent-context-box">
            <summary>
              <Layers size={14} /> 本对话已自动压缩上下文摘要
            </summary>
            <p>{contextPacket.layers.ephemeral.compacted.summary}</p>
            <small>
              已确认文案与规格始终从数据库读取，不依赖摘要猜测。
            </small>
          </details>
        )}

        <form
          className="agent-memory-form"
          onSubmit={(e) => {
            e.preventDefault();
            perform(async () => {
              if (editing)
                await api(path + "/" + editing.id, "PATCH", {
                  version: editing.version,
                  value,
                  expiresAt: expiresAt || null,
                });
              else
                await api(path, "POST", {
                  name,
                  value,
                  kind,
                  project: scope,
                  expiresAt: expiresAt || null,
                });
              reset();
            });
          }}
        >
          <h3>{editing ? "纠正记忆" : "添加已确认的记忆"}</h3>
          <div className="agent-memory-selects">
            <select
              disabled={!!editing}
              aria-label="记忆范围"
              value={scope}
              onChange={(e) => setScope(e.target.value)}
            >
              <option value="">所有对话（店铺长期）</option>
              {project && <option value={project}>仅「{projectName}」项目</option>}
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
            placeholder="名称，例如门店招牌、门店地址"
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
              placeholder="希望助理长期记住什么？（活动临时价格请关联项目或设有效期）"
              maxLength={240}
              value={value}
              onChange={(e) => setValue(e.target.value)}
            />
          )}
          <label className="agent-expiry-field">
            有效期（选填，到期自动停用）
            <input
              type="date"
              value={expiresAt}
              onChange={(e) => setExpiresAt(e.target.value)}
            />
          </label>
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
        <label className="agent-weeks-field">
          营销主题推荐
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
            <option value={1}>每周推荐</option>
            <option value={2}>每两周</option>
            <option value={3}>每三周</option>
            <option value={4}>每四周</option>
            <option value={0}>暂停自动推荐</option>
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
