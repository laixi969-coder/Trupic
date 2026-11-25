import React, { useState } from "react";
import {
  BookOpen,
  Check,
  Copy,
  Download,
  FileText,
  Film,
  Image as ImageIcon,
  RefreshCw,
  Scissors,
  Sparkles,
} from "lucide-react";
import { shapes } from "./CreationSpecs.jsx";
import { copyText } from "./ui.jsx";

export const states = {
  planning: "正在梳理需求",
  waiting_input: "需要补充",
  waiting_script: "准备脚本",
  waiting_copy: "选择文案",
  quoted: "等待确认",
  queued: "已排队",
  running: "正在制作",
  reviewing: "正在审核",
  failed: "制作未全部完成",
  cancelled: "已取消",
  delivered: "已交付",
};
export const kinds = {
  poster: "营销海报",
  copy: "推广文案",
  video: "宣传短片",
};

const STEPS = [
  { key: "plan", label: "梳理需求" },
  { key: "copy", label: "确认文案" },
  { key: "quote", label: "确认积分" },
  { key: "deliver", label: "制作交付" },
];

function stepIndex(status) {
  if (status === "planning" || status === "waiting_input") return 0;
  if (status === "waiting_copy" || status === "waiting_script") return 1;
  if (status === "quoted") return 2;
  if (["queued", "running", "reviewing", "delivered"].includes(status)) return 3;
  return -1;
}

export default function AgentTask({
  task: t,
  busy,
  writing,
  writingError,
  action,
  send,
  edit,
  tip,
  onOpenMemory,
}) {
  const [shortOption, setShortOption] = useState(0);
  const Icon = { poster: ImageIcon, copy: FileText, video: Film }[t.kind];
  const open = [
    "waiting_copy",
    "waiting_script",
    "quoted",
    "waiting_input",
    "planning",
  ].includes(t.status);
  const sendAction = (text, name, extra = {}) =>
    send(text, { action: name, task: t.id, revision: t.revision, ...extra });
  const activeStep = stepIndex(t.status);
  const doneAll = t.status === "delivered";

  const quickRevise = (item, text) => {
    const workRef = item?.work
      ? { id: item.work, version: item.version || 1 }
      : undefined;
    send(text, workRef ? { action: "new", workRef } : {}, {});
  };

  return (
    <section
      className={"agent-task status-" + t.status}
      aria-label={kinds[t.kind]}
    >
      <div className="agent-task-title">
        <span>
          <Icon size={18} />
          <strong>{t.workRef ? "修改" + kinds[t.kind] : kinds[t.kind]}</strong>
        </span>
        <small className={"agent-badge " + t.status}>{states[t.status]}</small>
      </div>
      <div className="agent-task-meta">
        <span className="agent-spec">
          {t.kind === "copy"
            ? "发布文案"
            : shapes[t.ratio] +
              " · " +
              (t.kind === "video" ? t.duration + " 秒" : t.imageCount + " 张")}
        </span>
        {t.recalledMemories?.length > 0 && (
          <button
            type="button"
            className="agent-recalled-pill"
            onClick={onOpenMemory}
            title="查看助理参考的记忆"
          >
            <BookOpen size={12} />
            已参考：{t.recalledMemories.slice(0, 2).map((m) => m.name).join("、")}
            {t.recalledMemories.length > 2 ? ` 等${t.recalledMemories.length}条` : ""}
          </button>
        )}
      </div>

      {activeStep >= 0 && (
        <ol className="agent-steps" aria-label="任务阶段">
          {STEPS.map((s, idx) => (
            <li
              key={s.key}
              className={
                doneAll || idx < activeStep
                  ? "done"
                  : idx === activeStep
                    ? "current"
                    : ""
              }
            >
              <span>{s.label}</span>
            </li>
          ))}
        </ol>
      )}

      {t.note && (
        <p className="agent-note-box" role="status">
          {t.note}
        </p>
      )}
      {t.concept && open && (
        <details>
          <summary>创意构思</summary>
          <p>{t.concept}</p>
        </details>
      )}
      {t.storyboard?.length > 0 && open && (
        <details>
          <summary>查看短片分镜</summary>
          {t.storyboard.map((shot, i) => (
            <p key={i}>{shot.line || shot.shot || shot.scene}</p>
          ))}
        </details>
      )}
      {writing && (
        <p className="agent-feedback" role="status">
          正在创作并复核，可以继续其他对话。
        </p>
      )}
      {writingError &&
        ["waiting_copy", "waiting_script"].includes(t.status) && (
          <p className="error" role="alert">
            {writingError}
          </p>
        )}
      {t.status === "waiting_script" && (
        <div className="agent-links">
          <button
            className="agent-chip-primary"
            disabled={busy || writing}
            onClick={() => action(t, "options")}
          >
            生成并复核脚本
          </button>
          <button disabled={busy} onClick={() => edit(t, true)}>
            使用我的文案
          </button>
        </div>
      )}
      {t.status === "waiting_copy" && (
        <div className="agent-choices">
          {t.options.map((o, i) => (
            <button
              key={i}
              className="agent-choice-card"
              disabled={busy}
              onClick={() =>
                sendAction("选第" + (i + 1) + "组", "select", { index: i })
              }
            >
              <span className="agent-choice-head">
                <small>方案 {i + 1}{o.angle ? ` · ${o.angle}` : ""}</small>
                <em>点此选用</em>
              </span>
              <b>{o.title}</b>
              <span className="agent-choice-body">{o.body}</span>
              {o.cta && <span className="agent-choice-cta">{o.cta}</span>}
            </button>
          ))}
          {!t.options.length && (
            <button
              className="secondary"
              disabled={busy || writing}
              onClick={() => action(t, "options")}
            >
              获取候选文案
            </button>
          )}
          <div className="agent-links">
            {t.options.length > 0 && (
              <button
                disabled={busy}
                onClick={() => sendAction("都由你决定", "select", { index: 0 })}
              >
                <Sparkles size={14} />
                都由你决定
              </button>
            )}
            <button disabled={busy} onClick={() => edit(t, true)}>
              使用我的文案
            </button>
          </div>
        </div>
      )}
      {t.locked && (
        <blockquote>
          {[t.locked.title, t.locked.body, t.locked.cta]
            .filter(Boolean)
            .join("\n")}
        </blockquote>
      )}
      {t.status === "quoted" && (
        <div className="agent-quote">
          <div className="agent-quote-summary">
            <span>{t.deliveries.join(" + ")}</span>
            <strong>{t.cost} 积分</strong>
          </div>
          {t.shortOptions?.length > 0 && (
            <fieldset className="agent-short-picker">
              <legend>没选就用短版，可随时修改</legend>
              {t.shortOptions.map((v, i) => (
                <label key={i} className={shortOption === i ? "selected" : ""}>
                  <input
                    type="radio"
                    name={"short-" + t.id}
                    checked={shortOption === i}
                    onChange={() => setShortOption(i)}
                  />
                  <span>{v}</span>
                </label>
              ))}
            </fieldset>
          )}
          <button
            className="primary agent-approve-btn"
            disabled={busy}
            onClick={() => action(t, "approve", null, shortOption)}
          >
            <Check size={17} />
            确认制作 · {t.cost} 积分
          </button>
          <small>
            排队时可取消；开始制作后自动完成，失败项自动退回积分。
          </small>
        </div>
      )}
      {open && (
        <div className="agent-links">
          {t.status === "planning" && (
            <button disabled={busy} onClick={() => action(t, "prepare")}>
              恢复规划
            </button>
          )}
          {t.status !== "planning" && (
            <button disabled={busy} onClick={() => edit(t, false)}>
              补充或修改
            </button>
          )}
          {t.status === "quoted" && (
            <button
              disabled={busy}
              onClick={() => sendAction("刷新报价", "refresh")}
            >
              刷新报价
            </button>
          )}
          <button disabled={busy} onClick={() => action(t, "cancel")}>
            取消任务
          </button>
        </div>
      )}
      {t.status === "queued" && t.items?.every((i) => i.state === "queued") && (
        <button
          className="textbtn"
          disabled={busy}
          onClick={() => action(t, "cancel")}
        >
          取消排队（退回积分）
        </button>
      )}
      {t.items?.map((i) => (
        <div className="agent-output" key={i.job}>
          <div className="agent-output-head">
            <strong>{i.label}</strong>
            {i.state !== "complete" && i.state !== "failed" && (
              <span className="agent-live-stage">
                {i.stage ||
                  (i.state === "queued"
                    ? "等待制作"
                    : i.state === "cancelled"
                      ? "已取消"
                      : "正在制作")}
              </span>
            )}
          </div>
          {i.state === "complete" ? (
            <>
              {i.video ? (
                <video
                  src={i.video}
                  poster={i.preview}
                  controls
                  muted
                  playsInline
                />
              ) : (
                i.preview && (
                  <a href={"#work/" + i.work} className="agent-preview-link">
                    <img src={i.preview} alt={i.label} />
                  </a>
                )
              )}
              {i.text && <p className="agent-copy-result">{i.text}</p>}
              <div className="agent-delivery-primary">
                {i.download && (
                  <a className="primary agent-dl-btn" href={i.download} download>
                    <Download size={16} />
                    保存成品
                  </a>
                )}
                {i.text && (
                  <button
                    type="button"
                    className="secondary agent-copy-btn"
                    onClick={async () =>
                      tip(
                        (await copyText(i.text))
                          ? "文案已复制"
                          : "请长按文案复制",
                      )
                    }
                  >
                    <Copy size={15} />
                    复制文案
                  </button>
                )}
              </div>
              <div className="agent-quick-edits">
                {i.kind !== "copy" && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => quickRevise(i, "换一张")}
                  >
                    <RefreshCw size={13} />
                    换一张
                  </button>
                )}
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => quickRevise(i, "文案短一点")}
                >
                  <Scissors size={13} />
                  文案短一点
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => quickRevise(i, "换个创意")}
                >
                  <Sparkles size={13} />
                  换个创意
                </button>
                <a href={"#work/" + i.work}>精修与旧版</a>
              </div>
            </>
          ) : i.state === "failed" ? (
            <div className="agent-failed-box">
              <p role="alert">生成失败，积分已退回。{i.error}</p>
              <button
                className="secondary"
                disabled={busy}
                onClick={() => action(t, "retry", i.job)}
              >
                重新制作 · 确认 {i.cost} 积分
              </button>
            </div>
          ) : null}
        </div>
      ))}
      {t.download && (
        <a className="secondary agent-bundle-dl" href={t.download} download>
          <Download size={16} />
          打包下载整套成品
        </a>
      )}
    </section>
  );
}
