import React, { useState } from "react";
import { Field } from "./ui.jsx";

const kinds = [
  ["text", "策划与文案"],
  ["vision", "商品与成品视觉审核"],
];

function PlatformForm({ platform, busy, act }) {
  const [form, set] = useState({ ...platform, key: "" });
  return (
    <form
      className="formpanel integration"
      onSubmit={async (event) => {
        event.preventDefault();
        if (await act("model-platform", form))
          set({ ...form, key: "", clearKey: false });
      }}
    >
      <h2>{platform.label || "新增兼容平台"}</h2>
      {platform.id.startsWith("custom-") && (
        <Field label="平台名称" name="label" form={form} set={set} limit={60} required />
      )}
      <Field
        label="Chat Completions 完整地址"
        name="url"
        form={form}
        set={set}
        limit={1200}
        required
      />
      {kinds.map(([kind, label]) => (
        <Field
          key={kind}
          label={label + "模型 ID"}
          name={kind}
          form={form}
          set={set}
          limit={180}
          placeholder={
            kind === "vision"
              ? "填写支持图片输入的模型 ID"
              : "填写平台提供的模型或推理接入点 ID"
          }
        />
      ))}
      <label className="field">
        API 密钥
        <input
          type="password"
          autoComplete="new-password"
          value={form.key}
          maxLength={2400}
          placeholder={
            platform.hasKey ? "已保存，地址相同可留空" : "本机服务可留空"
          }
          onChange={(event) => set({ ...form, key: event.target.value })}
        />
      </label>
      {!!platform.hasKey && (
        <label className="checkline">
          <input
            type="checkbox"
            checked={!!form.clearKey}
            onChange={(event) =>
              set({ ...form, clearKey: event.target.checked })
            }
          />
          清除已保存的密钥
        </label>
      )}
      <div className="modalfoot">
        <button className="primary" disabled={busy}>
          保存平台
        </button>
      </div>
    </form>
  );
}

export default function ModelPlatforms({ config, usage, busy, act }) {
  const { platforms, routes } = config;
  const [id, choose] = useState(platforms[0].id);
  const [draft, setDraft] = useState(null);
  const options = draft && !platforms.some(p => p.id === draft.id) ? [...platforms, draft] : platforms;
  const [selection, select] = useState({
    text: routes.text || "",
    vision: routes.vision || "",
  });
  const selected = options.find((p) => p.id === id);
  return (
    <>
      <label className="field">
        配置平台
        <select value={id} onChange={(event) => choose(event.target.value)}>
          {options.map((p) => (
            <option key={p.id} value={p.id}>
              {p.label || "新增兼容平台"}
            </option>
          ))}
        </select>
      </label>
      <button type="button" className="secondary" disabled={busy} onClick={() => {
        const extra = {id: "custom-" + crypto.randomUUID().replaceAll("-", ""), label: "", url: "", text: "", vision: "", hasKey: false};
        setDraft(extra);
        choose(extra.id);
      }}>新增兼容平台</button>
      <PlatformForm key={id} platform={selected} busy={busy} act={act} />
      <form
        className="formpanel integration"
        onSubmit={(event) => {
          event.preventDefault();
          act("model-routes", selection);
        }}
      >
        <h2>创作调用平台</h2>
        {kinds.map(([kind, label]) => (
          <label className="field" key={kind}>
            {label}
            <select
              aria-label={label}
              value={selection[kind]}
              onChange={(event) =>
                select({ ...selection, [kind]: event.target.value })
              }
            >
              <option value="">服务连接中的默认配置</option>
              {platforms
                .filter((p) => p[kind])
                .map((p) => (
                  <option value={p.id} key={p.id}>
                    {p.label} · {p[kind]}
                  </option>
                ))}
            </select>
          </label>
        ))}
        <p className="fineprint">
          视觉审核会将原图、海报和短片抽帧发送给选定模型。验证已保存的视觉连接会发送一张测试色卡。
        </p>
        <div className="modalfoot">
          <button
            type="button"
            className="secondary"
            disabled={busy}
            onClick={() => act("test-model", {})}
          >
            验证文案连接
          </button>
          <button
            type="button"
            className="secondary"
            disabled={busy}
            onClick={() => act("test-vision", {})}
          >
            验证视觉连接
          </button>
          <button className="primary" disabled={busy}>
            保存调用设置
          </button>
        </div>
      </form>
      <div className="sectionhead">
        <h2>今日模型调用</h2>
        <small>UTC</small>
      </div>
      {usage.length === 0 && <p className="muted">今天还没有模型请求记录。</p>}
      {usage.map((row) => (
        <div
          className="reviewrow"
          key={[row.platform, row.model, row.kind].join("/")}
        >
          <strong>
            {platforms.find((p) => p.id === row.platform)?.label || "默认连接"}{" "}
            · {row.model}
          </strong>
          <p>
            {row.kind === "vision" ? "视觉" : "文案"} · 请求 {row.calls} 次 ·
            有效响应 {row.succeeded} 次 · 平均 {(row.meanMs / 1000).toFixed(1)}{" "}
            秒
          </p>
          <small>
            输入 / 输出 token 为 {row.inputTokens ?? "未返回"} /{" "}
            {row.outputTokens ?? "未返回"}，平台分别返回了 {row.inputReports} /{" "}
            {row.outputReports} 次用量。
          </small>
        </div>
      ))}
    </>
  );
}
