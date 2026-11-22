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

export default function SkillLibrary({ skills = [] }) {
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
