import React, { useState } from "react";

const statusNames = {
  workflow: "本地素材包已接入",
  integrated: "创作方法已接入",
  reserve: "方法储备 · 尚未接入生成",
};
const stages = {
  copy: "文案指导",
  image: "画面指导",
  video: "视频指导",
  qa: "验收条件",
};

function Versions({ skill, busy, act }) {
  const [editing, setEditing] = useState(false);
  const [reason, setReason] = useState("");
  const [instructions, setInstructions] = useState(skill.instructions);
  const change = (action, n) => act("skill-version", { id: skill.id, action, n });
  const labels = { tested: "测试通过", failed: "未通过", pilot: "10% 灰度", live: "已发布", archived: "历史版本" };
  return <section>
    <button className="secondary" disabled={busy} onClick={()=>change(skill.enabled ? "disable" : "enable")}>{skill.enabled ? "暂停使用此方法" : "恢复使用此方法"}</button>
    <button className="secondary" onClick={() => {
      setInstructions(skill.instructions); setReason(""); setEditing(!editing);
    }}>{editing ? "收起编辑" : "修改并测试技能"}</button>
    {editing && <form className="formpanel" onSubmit={async e => {
      e.preventDefault();
      if (await act("skill-version", { id: skill.id, action: "test", instructions, reason })) setEditing(false);
    }}>
      {Object.entries(stages).map(([k,label]) => <label className="field" key={k}>{label}
        <textarea maxLength={900} value={instructions[k]} onChange={e => setInstructions({...instructions,[k]:e.target.value})} />
      </label>)}
      <label className="field">更新原因<input required maxLength={220} value={reason} onChange={e => setReason(e.target.value)} /></label>
      <button className="primary" disabled={busy}>运行固定测试</button>
    </form>}
    {skill.versions?.map(v => <details className="formpanel" key={v.n}>
      <summary>修订 {v.n} · {labels[v.status]} · {v.reason}</summary>
      <small>测试于 {new Date(v.created).toLocaleString()}{v.published && "，最近启用于 " + new Date(v.published).toLocaleString()}</small>
      {Object.entries(v.instructions).filter(([,value]) => value).map(([k,value]) => <p key={k}>{stages[k]} · {value}</p>)}
      {v.tests.map(t => <p key={t.name}>{t.name} · {t.ok ? "通过" : "未通过"}{t.changed?.length > 0 && " · 已更新" + t.changed.map(k => stages[k]).join("、")}</p>)}
      {["tested","archived"].includes(v.status) && <button className="secondary" disabled={busy} onClick={() => change("pilot",v.n)}>10% 灰度</button>}
      {["tested","pilot","archived"].includes(v.status) && <button className="secondary" disabled={busy} onClick={() => change(v.status === "archived" ? "rollback" : "release",v.n)}>{v.status === "archived" ? "回退到此修订" : "全量启用"}</button>}
    </details>)}
    {skill.versions?.some(v => ["live","pilot"].includes(v.status)) && <button className="textbtn" disabled={busy} onClick={() => change("rollback",0)}>{skill.media ? "停用上传技能" : "恢复内置版本"}</button>}
  </section>;
}

export default function SkillLibrary({ skills = [], busy, act }) {
  const [fileError, setFileError] = useState("");
  const template = {id:"custom_weekend",name:"周末邀约",kind:"poster",match:["周末邀约"],requires:["poster_design"],
    instructions:{copy:"围绕商家确认的活动写一句邀请。",image:"给商品与邀约标题分别留出位置。",video:"",qa:"逐字核对活动条件。"},reason:"首次导入"};
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const rows = skills.filter(
    (skill) =>
      (!status || skill.status === status) &&
      `${skill.name} ${skill.category} ${skill.source.title} ${skill.output}`
        .toLowerCase()
        .includes(query.toLowerCase().trim()),
  );
  return (
    <section className="skill-library">
      <h2>后台技能库</h2>
      <p>
        已保存 {skills.length}{" "}
        项方法。海报设计自动用于一句话海报创作；储备方法不会自动提交生成任务。
      </p>
      <p className="muted">
        Lovart 相关条目是根据公开展示编写的本地适配，未取得原始技能定义，不调用
        Lovart API。执行能力和限制分别记录。
      </p>
      <details className="formpanel">
        <summary>上传技能并测试</summary>
        <a download="skill.json" href={"data:application/json;charset=utf-8,"+encodeURIComponent(JSON.stringify(template,null,2))}>下载 JSON 示例</a>
        <label className="field">技能文件<input type="file" accept="application/json,.json" disabled={busy} onChange={async e => {
          const file=e.target.files?.[0]; e.target.value=""; if (!file) return;
          setFileError("");
          try {
            if (file.size > 32768) throw new Error("技能文件最大 32 KB。");
            const pack=JSON.parse(await file.text());
            await act("skill-import",pack);
          } catch (err) { setFileError(err.message); }
        }}/></label>
        {fileError && <p role="alert">{fileError}</p>}
      </details>
      <div className="skill-library-filters">
        <label>
          搜索方法
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="海报、封面、品牌…"
          />
        </label>
        <label>
          接入状态
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">全部状态</option>
            {Object.entries(statusNames).map(([key, name]) => (
              <option key={key} value={key}>
                {name}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p role="status">显示 {rows.length} 项</p>
      {rows.map((skill) => (
        <details key={skill.id} className="skill-library-entry">
          <summary>
            <strong>{skill.name}</strong>
            <span>
              {skill.category} · {statusNames[skill.status]}
            </span>
          </summary>
          <p>{skill.output}</p>
          <p>
            <strong>输入：</strong>
            {skill.inputs.join("、")}
          </p>
          {Object.entries(stages).map(
            ([key, label]) =>
              skill.instructions[key] && (
                <p key={key}>
                  <strong>{label}：</strong>
                  {skill.instructions[key]}
                </p>
              ),
          )}
          <p>
            <strong>当前范围：</strong>
            {skill.limits}
          </p>
          <p className="muted">
            版本 {skill.version} · {skill.source.kind} · 核对日期{" "}
            {skill.source.observed}
          </p>
          {skill.status !== "reserve" && <Versions skill={skill} busy={busy} act={act} />}
          {skill.source.url ? (
            <a href={skill.source.url} target="_blank" rel="noreferrer">
              参考来源：{skill.source.title}
            </a>
          ) : (
            <span>来源：Trupic 商家场景补充</span>
          )}
        </details>
      ))}
      {!rows.length && <p>没有匹配的方法，请调整搜索词或状态。</p>}
    </section>
  );
}
