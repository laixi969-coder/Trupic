import React, { useState } from "react";
import {
  Check,
  Download,
  FileText,
  Film,
  Image as ImageIcon,
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

export default function AgentTask({
  task: t,
  busy,
  writing,
  writingError,
  action,
  send,
  edit,
  tip,
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
  return (
    <section className="agent-task" aria-label={kinds[t.kind]}>
      <div className="agent-task-title">
        <span>
          <Icon size={19} />
          <strong>{t.workRef ? "修改" + kinds[t.kind] : kinds[t.kind]}</strong>
        </span>
        <small>{states[t.status]}</small>
      </div>
      <p className="agent-spec">
        {t.kind === "copy"
          ? "发布文案"
          : shapes[t.ratio] +
            " · " +
            (t.kind === "video" ? t.duration + " 秒" : t.imageCount + " 张")}
      </p>
      {t.note && <p role="status">{t.note}</p>}
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
              disabled={busy}
              onClick={() =>
                sendAction("选第" + (i + 1) + "组", "select", { index: i })
              }
            >
              <small>文案 {i + 1}</small>
              <b>{o.title}</b>
              <span>{o.body}</span>
              {o.cta && <span>{o.cta}</span>}
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
          <button
            className="textbtn"
            disabled={busy}
            onClick={() => edit(t, true)}
          >
            使用我的文案
          </button>
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
          <p>
            {t.deliveries.join(" + ")}
            <br />
            <strong>合计 {t.cost} 积分</strong>
          </p>
          {t.shortOptions?.length > 0 && (
            <fieldset>
              <legend>没选就用短版</legend>
              {t.shortOptions.map((v, i) => (
                <label key={i}>
                  <input
                    type="radio"
                    name={"short-" + t.id}
                    checked={shortOption === i}
                    onChange={() => setShortOption(i)}
                  />
                  {v}
                </label>
              ))}
            </fieldset>
          )}
          <button
            className="primary"
            disabled={busy}
            onClick={() => action(t, "approve", null, shortOption)}
          >
            <Check size={16} />
            确认制作 · {t.cost} 积分
          </button>
          <small>
            排队时可取消。开始制作后将继续执行，失败项自动退回积分。
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
          取消排队
        </button>
      )}
      {t.items?.map((i) => (
        <div className="agent-output" key={i.job}>
          <strong>{i.label}</strong>
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
                  <a href={"#work/" + i.work}>
                    <img src={i.preview} alt={i.label} />
                  </a>
                )
              )}
              {i.text && <p>{i.text}</p>}
              <div className="agent-links">
                <a href={i.download} download>
                  <Download size={15} />
                  下载
                </a>
                {i.text && (
                  <button
                    onClick={async () =>
                      tip(
                        (await copyText(i.text))
                          ? "文案已复制"
                          : "请长按文案复制",
                      )
                    }
                  >
                    复制文案
                  </button>
                )}
                <a href={"#work/" + i.work}>修改作品与查看旧版</a>
              </div>
            </>
          ) : i.state === "failed" ? (
            <>
              <p role="alert">生成失败，积分已退回。{i.error}</p>
              <button
                className="textbtn"
                disabled={busy}
                onClick={() => action(t, "retry", i.job)}
              >
                重新制作 · 确认 {i.cost} 积分
              </button>
            </>
          ) : (
            <p>
              {i.stage ||
                (i.state === "queued"
                  ? "等待制作"
                  : i.state === "cancelled"
                    ? "已取消"
                    : "正在制作")}
            </p>
          )}
        </div>
      ))}
      {t.download && (
        <a className="secondary" href={t.download} download>
          <Download size={16} />
          下载整套成品
        </a>
      )}
    </section>
  );
}
