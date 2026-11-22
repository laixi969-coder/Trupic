import React, { useEffect, useState } from "react";
import {
  ShieldCheck,
  BookOpen,
  GitBranch,
  History,
  Plus,
  RefreshCw,
  CheckCircle2,
  ExternalLink,
  Settings2,
  CalendarDays,
} from "lucide-react";
import { api, Blank, Busy, Field, Modal, PageHead, dateText } from "./ui.jsx";
const tabs = [
  ["works", "作品抽查", ShieldCheck],
  ["cases", "案例与方法", BookOpen],
  ["rules", "策略版本", GitBranch],
  ["audit", "审计日志", History],
  ["settings", "服务连接", Settings2],
  ["events", "本地活动", CalendarDays],
];
const states = {
  live: "全量启用",
  pilot: "10% 灰度",
  tested: "测试通过",
  failed: "测试未通过",
  archived: "历史版本",
  approved: "已入库",
  pending: "待审核",
};
export default function Admin({ tip }) {
  const [d, set] = useState(null),
    [tab, setTab] = useState("works"),
    [dialog, show] = useState(""),
    [f, form] = useState({}),
    [err, error] = useState(""),
    [busy, loading] = useState(false),
    [query, search] = useState("");
  const refresh = async () => set(await api("/admin"));
  useEffect(() => {
    refresh().catch((e) => error(e.message));
  }, []);
  function open(name, v = {}) {
    error("");
    form(v);
    show(name);
  }
  async function act(name, data) {
    if (busy) return;
    loading(true);
    error("");
    try {
      const r = await api("/admin/" + name, "POST", data);
      await refresh();
      show("");
      tip(
        name === "discover"
          ? "发现 " + r.count + " 个新参考"
          : name === "test-model"
            ? "模型连接成功"
            : "已保存管理操作",
      );
    } catch (e) {
      error(e.message);
    } finally {
      loading(false);
    }
  }
  const field = (n, l, opts = {}) => (
    <Field name={n} label={l} form={f} set={form} {...opts} />
  );
  return (
    <>
      <PageHead
        title="运营管理"
        desc="抽查作品、审核创意方法，管理测试与上线记录。"
      />
      <div className="adminnav">
        {tabs.map(([k, l, I]) => (
          <button
            key={k}
            className={k === tab ? "sel" : ""}
            onClick={() => {
              setTab(k);
              if (k === "settings") form({ ...d.settings, key: "" });
              error("");
            }}
          >
            <I size={15} />
            {l}
          </button>
        ))}
      </div>
      {!d ? (
        <p>{err || "正在载入…"}</p>
      ) : (
        <>
          {tab === "works" && (
            <>
              <div className="sectionhead">
                <h2>待抽查作品</h2>
                <small className="muted">
                  {d.jobs
                    .map(
                      (j) =>
                        ({
                          queued: "等待中",
                          running: "制作中",
                          complete: "已完成",
                          failed: "失败",
                        })[j.state] +
                        " " +
                        j.total,
                    )
                    .join(" · ")}
                </small>
              </div>
              {d.works.length ? (
                d.works.map((w) => (
                  <div className="adminrow" key={w.id}>
                    <div>
                      <b>{w.copy.title}</b>
                      <p>
                        版本 {w.n} · {dateText(w.created)} · {w.copy.engine}
                      </p>
                    </div>
                    <span className="pill">{w.rating || "待抽查"}</span>
                    <button
                      className="secondary"
                      onClick={() =>
                        open("review", { ...w, rating: w.rating || "合格" })
                      }
                    >
                      查看作品
                    </button>
                  </div>
                ))
              ) : (
                <Blank
                  title="暂无待抽查作品"
                  desc="商家生成作品后，优先展示待审与多次修改的作品。"
                />
              )}
            </>
          )}
          {tab === "cases" && (
            <>
              <div className="sectionhead">
                <h2>案例与方法库</h2>
                <div className="inline">
                  <button
                    className="secondary"
                    disabled={!d.feedConfigured || busy}
                    title="服务端配置授权订阅源后可同步"
                    onClick={() => act("discover", {})}
                  >
                    <RefreshCw size={14} />
                    同步来源
                  </button>
                  <button
                    className="primary"
                    onClick={() =>
                      open("case", { kind: "图片", category: "优秀案例" })
                    }
                  >
                    <Plus size={15} />
                    添加案例
                  </button>
                </div>
              </div>
              <input
                className="searchinput"
                placeholder="搜索类型、来源或创意方法"
                value={query}
                onChange={(e) => search(e.target.value)}
              />
              {d.cases
                .filter((c) =>
                  [c.title, c.kind, c.category, c.lesson, c.source]
                    .join(" ")
                    .includes(query),
                )
                .map((c) => (
                  <div className="adminrow" key={c.id}>
                    <div>
                      <b>{c.title}</b>
                      <p>
                        {c.kind} · {c.category} · {c.license}
                      </p>
                      <p>{c.lesson || "待补充方法拆解"}</p>
                      <a href={c.source} target="_blank" rel="noreferrer">
                        查看来源 <ExternalLink size={12} />
                      </a>
                    </div>
                    <span className="pill">{states[c.status]}</span>
                    {c.status === "pending" && (
                      <button
                        className="secondary"
                        onClick={() => open("approve", c)}
                      >
                        审核入库
                      </button>
                    )}
                  </div>
                ))}
              {!d.cases.length && (
                <Blank
                  icon={BookOpen}
                  title="还没有运营案例"
                  desc="记录来源和授权条件，审核后用于创意参考。"
                />
              )}
            </>
          )}
          {tab === "rules" && (
            <>
              {d.effects.length > 0 && (
                <div className="formpanel">
                  <h3>已核实的实际效果</h3>
                  {d.effects.map((e) => (
                    <div key={e.strategy} className="adminrow">
                      <div>
                        <b>{e.strategy}</b>
                        <p>
                          {e.reports} 条来源记录 · 展示 {e.views ?? "—"} · 点击{" "}
                          {e.clicks ?? "—"} · 咨询 {e.inquiries ?? "—"} · 到店{" "}
                          {e.visits ?? "—"}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              )}
              <div className="sectionhead">
                <h2>创意策略</h2>
                <button
                  className="primary"
                  onClick={() => open("rule", { method: "question" })}
                >
                  <Plus size={15} />
                  测试新版本
                </button>
              </div>
              {d.rules.map((r) => (
                <div className="adminrow" key={r.id}>
                  <div>
                    <b>{r.name}</b>
                    <p>{r.reason}</p>
                    <small>
                      {r.tests.length
                        ? r.tests.filter((t) => t.ok).length +
                          " / " +
                          r.tests.length +
                          " 个固定用例通过"
                        : "初始策略"}
                    </small>
                  </div>
                  <span className="pill">{states[r.status]}</span>
                  <button
                    className="secondary"
                    onClick={() => open("version", r)}
                  >
                    版本详情
                  </button>
                </div>
              ))}
            </>
          )}
          {tab === "settings" && (
            <form
              className="formpanel integration"
              onSubmit={(e) => {
                e.preventDefault();
                act("settings", f);
              }}
            >
              <div className="sectionhead">
                <h2>创作模型</h2>
                <span className="pill">{d.settings.engine}</span>
              </div>
              <p className="fineprint">
                可连接本机或已获授权的 Chat Completions
                服务。连接后，创作需求与商家已确认资料会发往该服务，用于文案生成及事实复核。
              </p>
              {field("url", "完整接口地址", {
                limit: 1200,
                placeholder: "https://…/v1/chat/completions",
              })}
              {field("model", "模型名称", {
                placeholder: "服务提供方的模型标识",
              })}
              <label className="field">
                API 密钥
                <input
                  autoComplete="off"
                  type="password"
                  placeholder={
                    d.settings.hasKey
                      ? "已配置，留空保留现有密钥"
                      : "本地服务可留空"
                  }
                  value={f.key || ""}
                  onChange={(e) => form({ ...f, key: e.target.value })}
                />
              </label>
              {d.settings.hasKey && (
                <label className="checkline">
                  <input
                    type="checkbox"
                    checked={!!f.clearKey}
                    onChange={(e) => form({ ...f, clearKey: e.target.checked })}
                  />
                  移除已保存的密钥
                </label>
              )}
              <div className="sectionhead">
                <h2>场景图像生成</h2>
              </div>
              <p className="fineprint">
                可连接支持 Images Generations 且返回 base64
                图片的服务，生成概念配图或摄影背景。商品主体仍取自商家原图。调用按服务商规则计费。
              </p>
              {field("imageUrl", "图像生成接口地址", {
                limit: 1200,
                placeholder: "https://…/v1/images/generations",
              })}
              {field("imageModel", "图像模型名称")}
              <label className="field">
                图像服务密钥
                <input
                  type="password"
                  autoComplete="off"
                  value={f.imageKey || ""}
                  placeholder={
                    d.settings.hasImageKey ? "已配置，留空保留" : "服务商密钥"
                  }
                  onChange={(e) => form({ ...f, imageKey: e.target.value })}
                />
              </label>
              <div className="sectionhead">
                <h2>授权案例订阅源</h2>
              </div>
              <p className="fineprint">
                从 RSS 或 Atom
                订阅索引发现候选案例。来源与引用条件保存在案例记录中，由管理员审核入库。
              </p>
              {field("feed", "订阅地址", {
                limit: 1200,
                placeholder: "https://…/feed.xml",
              })}
              {field("license", "授权或引用条件", { limit: 220 })}
              <div className="sectionhead">
                <h2>Pinterest 授权画板</h2>
              </div>
              <p className="fineprint">
                使用有读取权限的画板发现参考，只保存链接与案例方法。
              </p>
              {field("board", "画板 ID")}
              {field("pinRights", "画板内容的引用条件", { limit: 220 })}
              <label className="field">
                访问令牌
                <input
                  type="password"
                  autoComplete="off"
                  placeholder={
                    d.settings.hasPinToken
                      ? "已配置，留空保留"
                      : "Pinterest 只读访问令牌"
                  }
                  value={f.pinToken || ""}
                  onChange={(e) => form({ ...f, pinToken: e.target.value })}
                />
              </label>
              <div className="modalfoot">
                <button
                  className="secondary"
                  type="button"
                  disabled={busy}
                  onClick={() => act("test-model", {})}
                >
                  验证已保存的模型连接
                </button>
                <button className="primary" disabled={busy}>
                  保存配置
                </button>
              </div>
            </form>
          )}
          {tab === "events" && (
            <>
              <div className="sectionhead">
                <h2>已核实活动</h2>
                <button className="primary" onClick={() => open("event", {})}>
                  <Plus size={15} />
                  录入活动
                </button>
              </div>
              {d.events.length ? (
                d.events.map((e) => (
                  <div className="adminrow" key={e.id}>
                    <div>
                      <b>{e.title}</b>
                      <p>
                        {e.city} · {e.starts} 至 {e.ends}
                      </p>
                    </div>
                    <a href={e.source} target="_blank" rel="noreferrer">
                      活动来源 <ExternalLink size={12} />
                    </a>
                  </div>
                ))
              ) : (
                <Blank
                  icon={CalendarDays}
                  title="暂无已核实的本地活动"
                  desc="填写活动官方来源，符合地区和日期的商家会在每周选题中看到。"
                />
              )}
            </>
          )}
          {tab === "audit" && (
            <>
              <div className="sectionhead">
                <h2>操作记录</h2>
              </div>
              {d.audit.map((a, i) => (
                <div className="adminrow" key={i}>
                  <div>
                    <b>{a.action}</b>
                    <p>{a.target}</p>
                  </div>
                  <small>{new Date(a.created).toLocaleString("zh-CN")}</small>
                </div>
              ))}
            </>
          )}
        </>
      )}
      {err && !dialog && <p className="error">{err}</p>}
      {dialog && (
        <Modal
          title={
            {
              review: "抽查作品",
              case: "添加案例",
              approve: "审核创意方法",
              rule: "测试新策略",
              version: "策略版本详情",
              event: "录入已核实的活动",
            }[dialog]
          }
          onClose={() => show("")}
        >
          <form
            onSubmit={(e) => {
              e.preventDefault();
              act(dialog, f);
            }}
          >
            {dialog === "event" && (
              <>
                {field("title", "活动名称", { required: true })}
                {field("city", "所在地区", { required: true })}
                <div className="fieldgrid">
                  {[
                    ["starts", "开始日期"],
                    ["ends", "结束日期"],
                  ].map(([k, l]) => (
                    <label key={k} className="field">
                      {l}
                      <input
                        required
                        type="date"
                        value={f[k] || ""}
                        onChange={(e) => form({ ...f, [k]: e.target.value })}
                      />
                    </label>
                  ))}
                </div>
                {field("source", "活动官方来源 HTTPS 链接", {
                  required: true,
                  limit: 1000,
                })}
                <label className="checkline">
                  <input
                    required
                    type="checkbox"
                    checked={!!f.verified}
                    onChange={(e) => form({ ...f, verified: e.target.checked })}
                  />
                  已对照官方来源核实日期与地区
                </label>
              </>
            )}
            {dialog === "review" && (
              <>
                {f.kind === "video" ? (
                  <video
                    className="reviewvisual"
                    controls
                    src={"/api/admin/preview/" + f.id + "/" + f.n + "/video"}
                  />
                ) : (
                  <img
                    className="reviewvisual"
                    src={"/api/admin/preview/" + f.id + "/" + f.n + "/poster"}
                    alt={f.copy.title}
                  />
                )}
                <h3>{f.copy.title}</h3>
                <p className="pre">{f.copy.body}</p>
                {field("rating", "审核结论", {
                  options: ["优秀", "合格", "不合格"],
                })}
                {field("tags", "具体问题与修复建议", {
                  area: true,
                  limit: 160,
                })}
                <div className="fieldgrid">
                  {[
                    ["views", "实际展示"],
                    ["clicks", "实际点击"],
                    ["inquiries", "实际咨询"],
                    ["visits", "实际到店"],
                  ].map(([k, l]) => (
                    <label key={k} className="field">
                      {l}
                      <input
                        type="number"
                        min="0"
                        max="1000000000"
                        placeholder="选填"
                        value={f[k] ?? ""}
                        onChange={(e) => form({ ...f, [k]: e.target.value })}
                      />
                    </label>
                  ))}
                </div>
                {field("metrics", "已核实的实际效果及数据来源", {
                  area: true,
                  limit: 250,
                  placeholder:
                    "选填，如有实际到店、咨询记录，可填写统计周期和出处。",
                })}
              </>
            )}
            {dialog === "case" && (
              <>
                {field("title", "案例名称", { required: true })}
                <div className="fieldgrid">
                  {field("kind", "作品形式", {
                    options: ["图片", "文案", "视频"],
                  })}
                  {field("category", "案例类型", {
                    options: ["优秀案例", "反面案例", "创意方法"],
                  })}
                </div>
                {field("source", "原始来源网址", {
                  required: true,
                  limit: 1000,
                })}
                {field("license", "授权或引用条件", {
                  required: true,
                  limit: 220,
                })}
                {field("lesson", "可迁移的方法", {
                  required: true,
                  area: true,
                  limit: 300,
                })}
                {f.category === "反面案例" &&
                  field("issue", "具体问题", { required: true })}
              </>
            )}
            {dialog === "approve" && (
              <>
                <h3>{f.title}</h3>
                <p>{f.license}</p>
                {field("lesson", "可迁移的方法", {
                  required: true,
                  area: true,
                  limit: 300,
                })}
              </>
            )}
            {dialog === "rule" && (
              <>
                {field("name", "版本名称", { required: true })}
                <label className="field">
                  默认创意方法
                  <select
                    value={f.method}
                    onChange={(e) => form({ ...f, method: e.target.value })}
                  >
                    <option value="question">用问题开场</option>
                    <option value="invite">用邀请带出行动</option>
                    <option value="moment">从生活瞬间切入</option>
                  </select>
                </label>
                <label className="field">
                  关联创意方法
                  <select
                    value={f.case_id || ""}
                    onChange={(e) => form({ ...f, case_id: e.target.value })}
                  >
                    <option value="">使用内置方法</option>
                    {d.cases
                      .filter(
                        (c) =>
                          c.status === "approved" && c.category !== "反面案例",
                      )
                      .map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.title}
                        </option>
                      ))}
                  </select>
                </label>
                {field("reason", "更新原因", {
                  required: true,
                  area: true,
                  limit: 220,
                })}
                <p className="fineprint">
                  使用固定场景检验目标识别、版本差异和真实性拦截。通过后可灰度启用。
                </p>
              </>
            )}
            {dialog === "version" && (
              <>
                <span className="pill">{states[f.status]}</span>
                <h3>{f.name}</h3>
                <p>{f.reason}</p>
                {f.tests.map((t) => (
                  <div className="testrow" key={t.name}>
                    <CheckCircle2 size={15} />
                    {t.name}
                    <small>{t.ok ? "通过" : "未通过"}</small>
                  </div>
                ))}
                {["tested", "archived", "pilot"].includes(f.status) && (
                  <div className="modalfoot">
                    {f.status !== "pilot" && (
                      <button
                        type="button"
                        className="secondary"
                        disabled={busy}
                        onClick={() => act("pilot", f)}
                      >
                        10% 灰度启用
                      </button>
                    )}
                    <button
                      type="button"
                      className="primary"
                      disabled={busy}
                      onClick={() =>
                        act(f.status === "archived" ? "rollback" : "release", f)
                      }
                    >
                      {f.status === "archived" ? "回退到此版本" : "全量启用"}
                    </button>
                  </div>
                )}
              </>
            )}
            {err && <p className="error">{err}</p>}
            {dialog !== "version" && (
              <button disabled={busy} className="primary full">
                {busy ? (
                  <Busy />
                ) : (
                  {
                    event: "保存已核实活动",
                    review: "保存审核",
                    case: "提交待审",
                    approve: "确认入库",
                    rule: "运行固定测试",
                  }[dialog]
                )}
              </button>
            )}
          </form>
        </Modal>
      )}
    </>
  );
}
