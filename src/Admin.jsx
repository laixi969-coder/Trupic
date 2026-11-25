import React, { useEffect, useState } from "react";
import {
  ShieldCheck,
  ScanLine,
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
import ModelPlatforms from "./ModelPlatforms.jsx";
import SkillLibrary from "./SkillLibrary.jsx";
import Merchants from "./Merchants.jsx";
import { GrowthAdmin } from "./Growth.jsx";
import { FinanceAdmin } from "./Commerce.jsx";
import AdminPassword from "./AdminPassword.jsx";
const tabs = [
  ["dashboard","仪表盘",History],
  ["works", "作品抽查", ShieldCheck],
  ["visual", "成品视觉审核", ScanLine],
  ["cases", "案例与方法", BookOpen],
  ["skills", "技能库", BookOpen],
  ["rules", "策略版本", GitBranch],
  ["audit", "审计日志", History],
  ["platforms", "模型平台", Settings2],
  ["settings", "参考素材来源", Settings2],
  ["events", "营销日历", CalendarDays],
  ["merchants","商家与权限",Settings2],
  ["growth","渠道与增长",Settings2],
  ["finance","积分与套餐",Settings2],
  ["password", "管理密码", ShieldCheck],
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
    [tab, setTab] = useState("dashboard"),
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
        name === "event-sync" ? "已同步 " + r.count + " 个事件" : name === "discover"
          ? "发现 " + r.count + " 个新参考"
          : name === "test-model" || name === "test-vision"
            ? "模型连接成功"
            : "已保存管理操作",
      );
      return true;
    } catch (e) {
      error(e.message);
    } finally {
      loading(false);
    }
  }
  useEffect(()=>{
    if(d?.allowedTabs && !d.allowedTabs.includes(tab)) setTab(d.allowedTabs[0]);
  },[d,tab]);
  const field = (n, l, opts = {}) => (
    <Field name={n} label={l} form={f} set={form} {...opts} />
  );
  return (
    <>
      <PageHead
        title="运营管理"
        desc="抽查作品、审核创意方法，管理测试与上线记录。"
      />
      <div className="adminnav admin-sections">
        {tabs.filter(([k])=>!d?.allowedTabs||d.allowedTabs.includes(k)).map(([k, l, I]) => (
          <button
            key={k}
            className={k === tab ? "sel" : ""}
            aria-pressed={k === tab}
            onClick={() => {
              setTab(k);
              if (k === "settings" && d) form(Object.fromEntries(["feed", "license", "board", "pinRights"].map(key => [key, d.settings[key] || ""])));
              // Panels record their own actions; the log must show them when it is opened.
              if (k === "audit" && d) refresh().catch((e) => error(e.message));
              error("");
            }}
          >
            <I size={15} />
            {l}
          </button>
        ))}
      </div>
      {!d || (d.allowedTabs && !d.allowedTabs.includes(tab)) ? (
        <p>{err || "正在载入…"}</p>
      ) : (
        <>
          {tab === "dashboard" && <section className="formpanel"><h2>经营概览</h2><div className="datarows">
            {[["营销助理对话",d.assistantMetrics?.conversations ?? 0],["对话任务",d.assistantMetrics?.tasks ?? 0],["对话任务等待确认",d.assistantMetrics?.states.quoted ?? 0],["已核对模型账单（人民币）",d.costSummary.billed===null?"待对账":"¥"+(d.costSummary.billed/1000000).toFixed(2)],["已核对成本的任务",d.costSummary.reconciled],["云文件同步异常",d.costSummary.storageErrors],["今日注册商家", d.metrics.registrations],["今日发起创作的商家",d.metrics.active],["付费商家",d.metrics.payers],["累计实收（扣除全额退款）","¥"+(d.metrics.revenueCents/100).toFixed(2)],["已核对模型毛利（实收减已核对模型成本）",d.costSummary.billed===null?"待对账":"¥"+(d.metrics.revenueCents/100-d.costSummary.billed/1000000).toFixed(2)],["任务交付成功率",d.metrics.finished?(100*d.metrics.delivered/d.metrics.finished).toFixed(1)+"%":"暂无完成任务"],["注册后第七天创作留存",d.metrics.cohort?d.metrics.retained+" / "+d.metrics.cohort:"暂无到期商家"]].map(([k,v])=><div key={k}><span>{k}</span><b>{v}</b></div>)}
          </div></section>}
          {tab === "merchants" && <Merchants role={d.role} tip={tip}/>}
          {tab === "growth" && <GrowthAdmin tip={tip} />}
          {tab === "finance" && <FinanceAdmin tip={tip} />}
          {tab === "password" && <AdminPassword config={d.adminAuth} refresh={refresh} tip={tip} />}
          {tab === "skills" && <SkillLibrary skills={d.skills || []} busy={busy} act={act} />}
          {tab === "platforms" && (
            <ModelPlatforms
              config={d.modelPlatforms}
              usage={d.modelUsage}
              failures={d.modelFailures}
              costs={d.modelCosts}
              busy={busy}
              act={act}
            />
          )}
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
                      {w.reviewReasons.length > 0 && (
                        <p>{w.reviewReasons.join(" · ")}</p>
                      )}
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
          {tab === "visual" && (
            <section>
              <div className="sectionhead">
                <h2>成品视觉审核</h2>
                <button
                  className="secondary"
                  onClick={() => refresh().catch((e) => error(e.message))}
                >
                  刷新记录
                </button>
              </div>
              {!d.visualReviews.length && (
                <p>海报和短片生成后，这里会保留检查及修复记录。</p>
              )}
              {d.visualReviews.map((v) => (
                <details className="formpanel" key={v.id}>
                  <summary>
                    {
                      {
                        passed: "通过",
                        repaired: "已修复并通过",
                        repairing: "修复中",
                        blocked: "已拦截",
                      }[v.report.status]
                    }{" "}
                    · {v.kind === "video" ? "短片" : "海报"} · {v.brief}
                  </summary>
                  <p>
                    版本 {v.version} · {dateText(v.created)}
                  </p>
                  {v.report.attempts.map((a, i) => (
                    <div key={i}>
                      <b>{a.repair ? "自动修复后复检" : "初检"}</b>
                      {a.issues.length ? (
                        a.issues.map((issue, j) => <p key={j}>{issue}</p>)
                      ) : (
                        <p>通过</p>
                      )}
                    </div>
                  ))}
                  {v.report.content && (
                    <p>
                      {v.report.content.model} · {v.report.content.reason}
                    </p>
                  )}
                  {v.report.content?.compositionNote && (
                    <p>全幅画面观察 · {v.report.content.compositionNote}</p>
                  )}
                  {v.error && <p className="error">{v.error}</p>}
                  {v.state === "complete" && (
                    <a
                      href={
                        "/api/admin/preview/" +
                        v.work +
                        "/" +
                        v.version +
                        "/" +
                        (v.kind === "video" ? "video" : "poster")
                      }
                      target="_blank"
                      rel="noreferrer"
                    >
                      查看该版本成品
                    </a>
                  )}
                </details>
              ))}
            </section>
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
                placeholder="搜索案例、标签、适用场景或方法"
                value={query}
                onChange={(e) => search(e.target.value)}
              />
              {d.cases
                .filter((c) =>
                  [
                    c.title,
                    c.kind,
                    c.category,
                    c.tags,
                    c.scenario,
                    c.issue,
                    c.lesson,
                    c.source,
                  ]
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
                      {c.issue && <p>具体问题 · {c.issue}</p>}
                      {c.scenario && <p>适用场景 · {c.scenario}</p>}
                      {c.tags && <p>标签 · {c.tags}</p>}
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
                    <div key={e.strategyId || e.strategy} className="adminrow">
                      <div>
                        <b>{e.strategy}</b>
                        <p>
                          {e.reports} 条来源记录 · 展示 {e.views ?? "—"} · 点击{" "}
                          {e.clicks ?? "—"} · 咨询 {e.inquiries ?? "—"} · 到店{" "}
                          {e.visits ?? "—"}
                          {e.ctr != null &&
                            " · 点击率 " +
                              e.ctr +
                              "%（" +
                              e.ctrSamples +
                              " 条同时记录点击与展示）"}
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
                act("reference-settings", f);
              }}
            >
              <h2>参考素材来源</h2>
              <p className="fineprint">这里只配置案例与灵感来源。文案、图片、视频和视觉审核统一在「模型平台」配置。</p>
              <button type="button" className="secondary" onClick={() => setTab("platforms")}>前往模型平台</button>
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
                <button className="primary" disabled={busy}>
                  保存素材来源
                </button>
              </div>
            </form>
          )}
          {tab === "events" && (
            <>
              <div className="sectionhead">
                <h2>官方日历来源</h2>
                <button className="secondary" onClick={() => open("event-feed", { category: "本地活动" })}>添加来源</button>
              </div>
              {d.eventFeeds.map(feed => <div key={feed.id} className="adminrow">
                <div><b>{feed.name}</b><p>{feed.city} · {feed.category}{feed.keywords && " · " + feed.keywords}</p>
                  <small>{feed.enabled ? feed.checked ? "最近核验 " + dateText(feed.checked) : "待首次同步" : "已暂停"}</small>
                  {feed.error && <p className="error">{feed.error}</p>}
                  <a href={feed.url} target="_blank" rel="noreferrer">查看发布方日历</a>
                </div>
                {!!feed.enabled && <button disabled={busy} className="secondary" onClick={() => act("event-sync", { id: feed.id })}>立即同步</button>}
                <button disabled={busy} className="textbtn" onClick={() => act("event-toggle", { id: feed.id, enabled: !feed.enabled })}>{feed.enabled ? "暂停" : "启用"}</button>
              </div>)}
              <div className="sectionhead">
                <h2>已核实营销事件</h2>
                <button
                  className="primary"
                  onClick={() => open("event", { category: "本地活动" })}
                >
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
                        {e.category} · {e.city} · {e.starts} 至 {e.ends}
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
                  title="暂无已核实的营销事件"
                  desc="核实官方来源、地区和日期后，事件可以进入商家每周选题。"
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
                    {a.actor && (
                      <small>
                        操作人 ·{" "}
                        {a.actor === d.viewer
                          ? "本人"
                          : a.login ||
                            (a.actor === "payment-bridge"
                              ? "支付桥接"
                              : a.actor === "system"
                                ? "系统定时任务"
                                : "体验空间 " + a.actor.slice(0, 8))}
                      </small>
                    )}
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
              "event-feed": "添加官方日历来源",
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
            {dialog === "event-feed" && <>
              {field("name", "发布机构或日历名称", { required: true })}
              {field("url", "官方订阅地址（事件 JSON 或公告 RSS / Atom）", { required: true, limit: 1000 })}
              {field("city", "经营地区（公告可填“全部地区”）", { required: true })}
              {field("category", "事件类型", { options: ["本地活动", "节假日", "公开热点"] })}
              {field("keywords", "适用行业或经营关键词（多个用逗号分隔）", { required: f.category === "公开热点", limit: 160 })}
              <label className="checkline"><input type="checkbox" required checked={!!f.verified} onChange={e => form({ ...f, verified: e.target.checked })} />已核实官方发布方及订阅使用条件</label>
            </>}
            {dialog === "event" && (
              <>
                {field("category", "事件类型", {
                  options: ["本地活动", "节假日", "公开热点"],
                })}
                {field("title", "事件名称", { required: true })}
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
                {(f.quality || [])
                  .filter((q) =>
                    [
                      "成品视觉审核",
                      "自动修复",
                      "商品原图比对",
                      "画面语义复核",
                    ].includes(q.label),
                  )
                  .map((q) => (
                    <p key={q.label}>
                      {q.label} · {q.detail}
                    </p>
                  ))}
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
            {(dialog === "case" || dialog === "approve") && (
              <>
                {field("scenario", "适用场景", { limit: 200 })}
                {field("tags", "检索标签", { limit: 160 })}
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
                {f.case_id && f.status !== "failed" && (
                  <button
                    type="button"
                    className="secondary"
                    disabled={busy}
                    onClick={() =>
                      act("retrieval", { id: f.id, enabled: !f.retrievable })
                    }
                  >
                    {f.retrievable
                      ? "停用跨案例检索"
                      : "允许按场景与标签检索此方法"}
                  </button>
                )}
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
                    event: "保存已核实营销事件",
                    "event-feed": "保存日历来源",
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
