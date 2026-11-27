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
  const [newPrice, setNewPrice] = useState("");
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
      {t.productNarration && t.locked && open ? (
        <div className="agent-locked-tiers">
          <strong>逐镜口播</strong>
          {t.storyboard.map((s) => (
            <p key={s.start}><small>{s.start}–{s.end} 秒</small>　{s.narration || "仅展示商品"}</p>
          ))}
        </div>
      ) : t.storyboard?.length > 0 && open && (
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
              {o.shareTo && (
                <small className="agent-choice-social">
                  社交货币：适合发给「{o.shareTo}」
                  {o.reply ? ` · 对方会接「${o.reply}」` : ""}
                </small>
              )}
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
      {t.locked && !t.productNarration && (
        <div className="agent-locked-tiers">
          <blockquote>
            {[t.locked.title, t.locked.body, t.locked.cta]
              .filter(Boolean)
              .join("\n")}
          </blockquote>
          {t.locked.socialPost && (
            <div className="agent-social-post">
              <div className="agent-social-post-head">
                <small>配发社媒正文（朋友圈 / 小红书）</small>
                <button
                  type="button"
                  onClick={async () =>
                    tip(
                      (await copyText(t.locked.socialPost))
                        ? "发帖正文已复制"
                        : "请长按复制",
                    )
                  }
                >
                  <Copy size={12} />
                  复制发帖文案
                </button>
              </div>
              <p>{t.locked.socialPost}</p>
            </div>
          )}
        </div>
      )}
      {t.status === "quoted" && (
        <div className="agent-quote">
          {t.videoMotion && <p>{t.videoMotion === "economy" ? "H3 经济动态背景 · 商品与字幕本地合成" : "本地商品运镜 · 无视频模型调用"}</p>}
          {t.merchantOffer && (
            <div className="agent-offer-summary">
              <strong>{t.merchantOffer.product} · {t.merchantOffer.weekday}{t.merchantOffer.channel}价</strong>
              <p>{t.previousOffer && t.previousOffer.amount !== t.merchantOffer.amount && (
                <><del>¥{t.previousOffer.amount}</del> → </>)}¥{t.merchantOffer.amount}</p>
              <small>这次确认的金额用于活动海报、口播、字幕和配文。</small>
            </div>
          )}
          {t.productNarration && t.storyboard?.at(-1)?.narration && (
            <fieldset className="agent-ending-picker">
              <legend>片尾读法</legend>
              <p>「{t.storyboard.at(-1).narration}」</p>
              {t.endingTakes?.length ? t.endingTakes.map((take) => (
                <div key={take.style} className="agent-ending-take">
                  <button type="button" disabled={busy} aria-pressed={t.selectedEnding === take.style}
                    onClick={() => action(t, "ending-choice", take.style)}>
                    {t.selectedEnding === take.style ? "已选" : "选用"}{take.label}
                  </button>
                  <audio controls preload="none" aria-label={take.label} src={take.url} />
                </div>
              )) : <button type="button" disabled={busy} onClick={() => action(t, "ending-previews")}>
                {busy === "ending-previews" ? "正在生成试听…" : "试听两种片尾读法"}
              </button>}
            </fieldset>
          )}
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
            disabled={busy || (t.voiceRevision && !t.selectedEnding)}
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
          {t.status === "quoted" && t.productNarration && (
            <button disabled={busy} onClick={() => edit(t, true)}>改口播台词</button>
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
                  muted={!i.subtitles}
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
              {i.offerReadback && (
                <details>
                  <summary>查看交付核对记录</summary>
                  <p>海报读字　{i.offerReadback.poster}</p>
                  <p>成片听写　{i.offerReadback.spoken}</p>
                  <p>画面字幕　{i.offerReadback.burned}</p>
                  <p>字幕文件　{i.offerReadback.subtitles}</p>
                  <p>发布配文　{i.offerReadback.post}</p>
                </details>
              )}
              <div className="agent-delivery-primary">
                {i.download && (
                  <a className="primary agent-dl-btn" href={i.download} download>
                    <Download size={16} />
                    保存成品
                  </a>
                )}
                {i.subtitles && (
                  <a className="secondary agent-copy-btn" href={i.subtitles} download>
                    下载字幕
                  </a>
                )}
                {i.offerPoster && <a className="secondary agent-copy-btn" href={i.offerPoster} download>保存活动海报</a>}
                {i.post && <a className="secondary agent-copy-btn" href={i.post} download>保存发布配文</a>}
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
                <a href={"#blind-setup/" + i.work + "/" + (i.version || 1)}>{i.version > 1 ? "盲评这两版" : "评价首稿"}</a>
                {i.subtitles && (
                  <button type="button" disabled={busy} onClick={() => quickRevise(i, "只换片尾口吻")}>
                    只换片尾口吻
                  </button>
                )}
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
              {i.offerPoster && t.merchantOffer && (
                <form className="agent-offer-edit" onSubmit={(e) => {
                  e.preventDefault();
                  quickRevise(i, t.merchantOffer.weekday + "价从" + t.merchantOffer.amount + "改成" + newPrice + "，试听两种片尾读法");
                }}>
                  <label>{t.merchantOffer.weekday}新价（元）
                    <input inputMode="decimal" required pattern="[0-9]{1,8}(\.[0-9]{1,2})?"
                      value={newPrice} placeholder={t.merchantOffer.amount} onChange={(e) => setNewPrice(e.target.value)} />
                  </label>
                  <button type="submit" disabled={busy || !newPrice}>改价并试听片尾</button>
                </form>
              )}
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
