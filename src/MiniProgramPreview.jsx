import React, { useEffect, useRef, useState } from "react";
import {
  ArrowUp,
  BookOpen,
  Camera,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Headphones,
  Home,
  Images,
  LoaderCircle,
  Mic,
  MoreHorizontal,
  Plus,
  Sparkles,
  Square,
  User,
  Volume2,
  X,
  Zap,
} from "lucide-react";
import { api } from "./ui.jsx";
import AgentTask, { states } from "./AgentTask.jsx";
import AgentMemory from "./AgentMemory.jsx";
import "./mp.css";

const root = "/agent/conversations";
const activeStates = ["planning", "queued", "running", "reviewing"];
const uid = () =>
  globalThis.crypto?.randomUUID?.() ||
  Date.now().toString(36) + Math.random().toString(36).slice(2);

export default function MiniProgramPreview({
  data,
  refresh,
  tip,
  onGo,
  onOpenCredits,
  onOpenAccount,
}) {
  const [tab, setTab] = useState("home"); // home | works | mine
  const [screen, setScreen] = useState("home"); // home | chat
  const [home, setHome] = useState({
    conversations: [],
    projects: [],
    weeks: 1,
    pending: null,
    candidateCount: 0,
  });
  const [chat, setChat] = useState(null);
  const [text, setText] = useState("");
  const [asset, setAsset] = useState(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [showHistory, setShowHistory] = useState(false);
  const [showMemory, setShowMemory] = useState(false);
  const [writing, setWriting] = useState({});
  const [writingErrors, setWritingErrors] = useState({});
  const [recording, setRecording] = useState(false);
  const [callMode, setCallMode] = useState(false);

  const fileRef = useRef(null);
  const speechRef = useRef(null);
  const endRef = useRef(null);
  const live = useRef(true);
  const speechApi = window.SpeechRecognition || window.webkitSpeechRecognition;

  const syncHome = async () => {
    const h = await api("/agent");
    if (live.current) setHome(h);
    return h;
  };

  useEffect(() => {
    live.current = true;
    syncHome().catch((e) => live.current && setError(e.message));
    return () => {
      live.current = false;
      speechRef.current?.abort();
    };
  }, [data.workspace]);

  const chatId = chat?.id;
  const hasRunning = (chat?.tasks || []).some((t) =>
    activeStates.includes(t.status),
  );
  useEffect(() => {
    if (!chatId || screen !== "chat") return;
    let alive = true,
      timer;
    const tick = async () => {
      try {
        const snap = await api(root + "/" + chatId);
        if (alive) setChat(snap);
        if (
          alive &&
          hasRunning &&
          !(snap.tasks || []).some((t) => activeStates.includes(t.status))
        ) {
          await refresh();
          await syncHome();
        }
      } catch {}
      if (alive) timer = setTimeout(tick, hasRunning ? 2000 : 12000);
    };
    timer = setTimeout(tick, hasRunning ? 1500 : 12000);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [chatId, screen, hasRunning]);

  async function run(label, fn) {
    if (busy) return;
    setBusy(label);
    setError("");
    try {
      await fn();
    } catch (e) {
      if (live.current) setError(e.message);
    } finally {
      if (live.current) setBusy("");
    }
  }

  async function openChat(id) {
    await run("open", async () => {
      const c = await api(root + "/" + id + "/visit", "POST", {});
      setChat(c);
      setShowHistory(false);
      setScreen("chat");
      setTab("home");
    });
  }

  async function startNewChat() {
    await run("new", async () => {
      const c = await api(root, "POST", {});
      setChat(c);
      setText("");
      setAsset(null);
      setShowHistory(false);
      setScreen("chat");
      await syncHome();
    });
  }

  async function generateOptions(cid, t) {
    const id = t.id,
      rev = t.revision;
    setWriting((old) => ({ ...old, [id]: rev }));
    setWritingErrors((old) => ({ ...old, [id]: null }));
    try {
      const next = await api("/agent/tasks/" + id + "/options", "POST", {
        revision: rev,
      });
      if (live.current) {
        setChat((c) =>
          c?.id === cid
            ? {
                ...c,
                tasks: c.tasks.map((card) =>
                  card.id === id && card.revision === rev ? next : card,
                ),
              }
            : c,
        );
      }
    } catch (e) {
      if (live.current)
        setWritingErrors((old) => ({
          ...old,
          [id]: { revision: rev, message: e.message },
        }));
    } finally {
      if (live.current)
        setWriting((old) => (old[id] === rev ? { ...old, [id]: null } : old));
    }
  }

  async function send(rawText, extra = {}, customOpts = null) {
    const content = (rawText ?? text).trim();
    const finalText = content || (asset ? "用这张商品图做一张海报" : "");
    if (!finalText) return;
    await run("send", async () => {
      const c =
        screen === "chat" && chat ? chat : await api(root, "POST", {});
      const opts =
        customOpts ??
        (asset ? { asset: asset.id, assetMode: "original" } : {});
      const body = { text: finalText, options: opts, requestKey: uid(), ...extra };
      if (!extra.action && c.tasks?.length) {
        const latest = c.tasks.at(-1);
        body.task = latest.id;
        body.revision = latest.revision;
      }
      const reply = await api(root + "/" + c.id + "/messages", "POST", body);
      setChat(reply);
      setScreen("chat");
      setText("");
      setAsset(null);
      await syncHome();
      requestAnimationFrame(() =>
        endRef.current?.scrollIntoView({ behavior: "smooth" }),
      );
      const latest = reply.tasks?.at(-1);
      if (
        (latest?.status === "waiting_copy" ||
          latest?.status === "waiting_script") &&
        !latest.options.length
      ) {
        generateOptions(reply.id, latest);
      }
      if (callMode) speakLatest(reply);
    });
  }

  function speakLatest(c) {
    const last = [...(c?.messages || [])]
      .reverse()
      .find((m) => m.role === "assistant" && m.text);
    if (!last?.text || !window.speechSynthesis) return;
    try {
      window.speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(last.text.slice(0, 180));
      u.lang = "zh-CN";
      window.speechSynthesis.speak(u);
    } catch {}
  }

  async function action(t, verb, job, option = 0) {
    if (verb === "options") return generateOptions(chat.id, t);
    await run(verb, async () => {
      if (verb === "retry") await api("/jobs/" + job + "/retry", "POST", {});
      else
        await api("/agent/tasks/" + t.id + "/" + verb, "POST", {
          option,
          revision: t.revision,
          quoteId: t.quoteId,
          confirmedCost: t.cost,
          approvalType: "production",
          requestKey: "approve-" + t.quoteId,
        });
      setChat(await api(root + "/" + chat.id));
      await syncHome();
      await refresh();
    });
  }

  async function decideCandidate(cand, accept) {
    await run("mem", async () => {
      await api(
        "/agent/memory/" + cand.id + (accept ? "/confirm" : "/dismiss"),
        "POST",
        { version: cand.version },
      );
      if (chat) setChat(await api(root + "/" + chat.id));
      await syncHome();
      tip(accept ? `已记住「${cand.name}」` : "已忽略");
    });
  }

  async function onPickPhoto(e) {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    await run("upload", async () => {
      const form = new FormData();
      form.append("image", f);
      const uploaded = await api("/assets", "POST", form);
      setAsset(uploaded);
      await refresh();
    });
  }

  function toggleVoice(continuous = false) {
    if (recording) {
      speechRef.current?.stop();
      setRecording(false);
      if (!continuous) setCallMode(false);
      return;
    }
    if (!speechApi) {
      setError("当前浏览器不支持语音听写，请直接打字或使用微信真机体验。");
      return;
    }
    const rec = new speechApi();
    speechRef.current = rec;
    rec.lang = "zh-CN";
    rec.onresult = (e) => {
      const spoken = e.results[0][0].transcript;
      if (continuous) {
        send(spoken);
      } else {
        setText((v) => (v + spoken).slice(0, 1200));
      }
    };
    rec.onend = () => setRecording(false);
    rec.onerror = () => {
      setRecording(false);
      setError("没有听清楚，请再点一次麦克风。");
    };
    try {
      rec.start();
      setRecording(true);
      if (continuous) {
        setCallMode(true);
        setScreen("chat");
      }
    } catch {
      setError("无法开启麦克风。");
    }
  }

  const messages = chat?.messages || [];
  const latestCard = new Map(
    messages.filter((m) => m.kind === "task").map((m) => [m.task, m.seq]),
  );
  const cards = new Map((chat?.tasks || []).map((t) => [t.id, t]));
  const pendingCand = chat?.candidates?.[0] || null;

  return (
    <div className="mp-stage">
      <div className="mp-desktop-bar">
        <span>微信小程序 V4 实时体验（390 × 844 · 连接本机真实后端）</span>
        <button type="button" onClick={() => onGo("home")}>
          切换到桌面网页版
        </button>
      </div>

      <div className="mp-phone" role="application" aria-label="响指出片小程序">
        {/* Authentic WeChat Mini Program Nav Bar */}
        <header className="mp-wx-nav">
          <div className="mp-wx-left">
            {screen === "chat" && tab === "home" && (
              <button
                type="button"
                className="mp-back-btn"
                onClick={() => {
                  setCallMode(false);
                  speechRef.current?.abort();
                  setScreen("home");
                  syncHome().catch(() => {});
                }}
              >
                <ChevronLeft size={19} />
                返回
              </button>
            )}
          </div>
          <strong className="mp-wx-title">
            {tab === "works"
              ? "我的作品"
              : tab === "mine"
                ? "我的"
                : screen === "chat"
                  ? "营销助理"
                  : "响指出片 Trupic"}
          </strong>
          <div className="mp-wx-capsule" aria-hidden="true">
            <MoreHorizontal size={15} />
            <i />
            <span className="mp-wx-dot" />
          </div>
        </header>

        <input
          type="file"
          accept="image/jpeg,image/png,image/webp"
          ref={fileRef}
          hidden
          onChange={onPickPhoto}
        />

        {/* Body */}
        <div className="mp-body">
          {tab === "home" && screen === "home" && (
            <div className="mp-home">
              <div className="mp-home-bar">
                <div className="mp-home-brand">
                  <img src="/favicon.svg" alt="" />
                  <b>营销助理</b>
                </div>
                <div className="mp-home-actions">
                  <button
                    type="button"
                    onClick={() => setShowMemory(true)}
                  >
                    <BookOpen size={15} />
                    记忆
                    {home.candidateCount > 0 && <i className="mp-dot" />}
                  </button>
                  <button
                    type="button"
                    onClick={async () => {
                      await syncHome();
                      setShowHistory((v) => !v);
                    }}
                  >
                    <Clock3 size={15} />
                    历史对话
                  </button>
                </div>
              </div>

              {showHistory && (
                <div className="mp-history-sheet">
                  <div className="mp-sheet-head">
                    <b>历史对话</b>
                    <button type="button" onClick={() => setShowHistory(false)}>
                      <X size={16} />
                    </button>
                  </div>
                  {home.conversations.length === 0 ? (
                    <p className="mp-muted">还没有对话记录。</p>
                  ) : (
                    home.conversations.map((c) => (
                      <button
                        key={c.id}
                        type="button"
                        className="mp-hist-row"
                        onClick={() => openChat(c.id)}
                      >
                        <span>{c.title}</span>
                        {c.activeStatus && <em>{states[c.activeStatus]}</em>}
                      </button>
                    ))
                  )}
                </div>
              )}

              <div className="mp-hero-row">
                <div className="mp-hero-copy">
                  <h1>
                    {asset ? "这张图，" : "今天想"}
                    <br />
                    {asset ? "想怎么发？" : "推广什么？"}
                  </h1>
                  <p>
                    {recording
                      ? "正在听，说完点一下结束。"
                      : "点麦克风，说完可以改字。"}
                  </p>
                </div>
                <button
                  type="button"
                  className={"mp-mic-disc " + (recording ? "listening" : "")}
                  disabled={!!busy}
                  onClick={() => toggleVoice(false)}
                >
                  <div>
                    {recording ? <Square size={22} /> : <Mic size={24} />}
                    <span>{recording ? "结束" : "说需求"}</span>
                  </div>
                </button>
              </div>

              {asset && (
                <div className="mp-photo-box">
                  <img src={asset.original} alt={asset.name} />
                  <div>
                    <span>{asset.name}</span>
                    <button type="button" onClick={() => setAsset(null)}>
                      移除
                    </button>
                  </div>
                </div>
              )}

              <div className="mp-compose-card">
                <textarea
                  rows={3}
                  maxLength={1200}
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  placeholder={
                    asset
                      ? "给这张商品图补一句需求…"
                      : "也可以打字，说说店里要推什么…"
                  }
                />
                <div className="mp-compose-foot">
                  <button
                    type="button"
                    className="mp-photo-btn"
                    disabled={!!busy}
                    onClick={() => fileRef.current?.click()}
                  >
                    <Camera size={16} />
                    {asset ? "换照片" : "拍照 / 选图"}
                  </button>
                  <button
                    type="button"
                    className="mp-send-btn"
                    disabled={!!busy || !(text.trim() || asset)}
                    onClick={() => send()}
                  >
                    {busy === "send" ? (
                      <LoaderCircle size={15} className="spin" />
                    ) : (
                      <>
                        {asset && !text.trim() ? "用图做海报" : "发送"}
                        <ArrowUp size={15} />
                      </>
                    )}
                  </button>
                </div>
              </div>

              {error && <p className="mp-error">{error}</p>}

              <button
                type="button"
                className="mp-call-row"
                onClick={() => toggleVoice(true)}
              >
                <span className="mp-call-icon">
                  <Headphones size={18} />
                </span>
                <div>
                  <b>连续语音对话</b>
                  <small>停顿后自动发送，助理会朗读回复</small>
                </div>
                <ChevronRight size={17} />
              </button>

              <div className="mp-resume-section">
                <h2>接着做</h2>
                {home.pending ? (
                  <button
                    type="button"
                    className="mp-pending-dark"
                    onClick={() => openChat(home.pending.conversation)}
                  >
                    <div className="mp-pending-top">
                      <span>
                        <i />
                        {states[home.pending.status] || "进行中"}
                      </span>
                      {home.pending.cost != null && (
                        <b>{home.pending.cost} 积分</b>
                      )}
                    </div>
                    <div className="mp-pending-btm">
                      <span>{home.pending.title || "未完成的创作任务"}</span>
                      <em>
                        {home.pending.status === "quoted" ? "核对报价" : "继续"} ›
                      </em>
                    </div>
                  </button>
                ) : (
                  <p className="mp-empty-box">暂无待处理的任务</p>
                )}
              </div>

              <button
                type="button"
                className="mp-legacy-row"
                onClick={() => onGo("studio")}
              >
                <span>实拍朋友圈与其他创作</span>
                <ChevronRight size={16} />
              </button>
            </div>
          )}

          {tab === "home" && screen === "chat" && (
            <div className="mp-chat">
              <div className="mp-chat-head">
                <h2>{chat?.title || "新对话"}</h2>
                <div>
                  <button
                    type="button"
                    onClick={async () => {
                      await syncHome();
                      setShowHistory((v) => !v);
                    }}
                  >
                    历史
                  </button>
                  <button type="button" onClick={startNewChat}>
                    <Plus size={14} />
                    新对话
                  </button>
                </div>
              </div>

              {showHistory && (
                <div className="mp-history-sheet">
                  {home.conversations.map((c) => (
                    <button
                      key={c.id}
                      type="button"
                      className="mp-hist-row"
                      onClick={() => openChat(c.id)}
                    >
                      <span>{c.title}</span>
                      {c.activeStatus && <em>{states[c.activeStatus]}</em>}
                    </button>
                  ))}
                </div>
              )}

              <div className="mp-turns">
                {messages.map((m) => {
                  if (m.kind === "task") {
                    if (latestCard.get(m.task) !== m.seq) return null;
                    const t = cards.get(m.task);
                    return (
                      t && (
                        <AgentTask
                          key={m.seq}
                          task={t}
                          busy={!!busy}
                          writing={writing[t.id] === t.revision}
                          writingError={
                            writingErrors[t.id]?.revision === t.revision
                              ? writingErrors[t.id].message
                              : ""
                          }
                          action={action}
                          send={(txt, ex, op) => send(txt, ex, op)}
                          edit={() => {}}
                          tip={tip}
                          onOpenMemory={() => setShowMemory(true)}
                        />
                      )
                    );
                  }
                  if (m.kind === "topics")
                    return (
                      <div className="mp-bubble assistant" key={m.seq}>
                        <b>本周可以做什么</b>
                        {m.items.map((r, i) => (
                          <button
                            key={r.topicId}
                            type="button"
                            className="mp-topic-btn"
                            onClick={() =>
                              send(
                                r.brief,
                                { action: "new" },
                                { topicId: r.topicId },
                              )
                            }
                          >
                            {i + 1}. {r.title} ›
                          </button>
                        ))}
                      </div>
                    );
                  if (m.kind === "switch")
                    return (
                      <div className="mp-bubble assistant" key={m.seq}>
                        这是新任务，要在哪里继续？
                        <div className="mp-inline-row">
                          <button
                            type="button"
                            className="agent-chip-primary"
                            onClick={() =>
                              send(m.text, { action: "branch" }, m.options)
                            }
                          >
                            另开对话
                          </button>
                          <button
                            type="button"
                            onClick={() =>
                              send(m.text, { action: "here" }, m.options)
                            }
                          >
                            留在这里
                          </button>
                        </div>
                      </div>
                    );
                  return (
                    <div className={"mp-bubble " + m.role} key={m.seq}>
                      {m.asset && (
                        <img
                          className="mp-msg-img"
                          src={"/api/assets/" + m.asset + "/original"}
                          alt=""
                        />
                      )}
                      <div>{m.text}</div>
                      {m.recalled?.length > 0 && (
                        <small className="mp-recalled">
                          已参考记忆：{m.recalled.map((r) => r.name).join("、")}
                        </small>
                      )}
                    </div>
                  );
                })}
                <div ref={endRef} />
              </div>

              {messages.length > 0 && (
                <div className="mp-speak-row">
                  <button type="button" onClick={() => speakLatest(chat)}>
                    <Volume2 size={14} />
                    朗读最近回复
                  </button>
                </div>
              )}

              {pendingCand && (
                <div className="mp-cand-card">
                  <span>
                    <Sparkles size={13} />
                    长期记住吗？<b>{pendingCand.name}</b>：{pendingCand.value}
                  </span>
                  <div>
                    <button
                      type="button"
                      className="agent-chip-primary"
                      onClick={() => decideCandidate(pendingCand, true)}
                    >
                      记住
                    </button>
                    <button
                      type="button"
                      onClick={() => decideCandidate(pendingCand, false)}
                    >
                      不用
                    </button>
                  </div>
                </div>
              )}

              <div className="mp-compose-card compact">
                {asset && (
                  <div className="mp-photo-box">
                    <img src={asset.original} alt="" />
                    <span>{asset.name}</span>
                    <button type="button" onClick={() => setAsset(null)}>
                      移除
                    </button>
                  </div>
                )}
                <textarea
                  rows={2}
                  maxLength={1200}
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  placeholder="商品、活动，或想调整的地方…"
                />
                <div className="mp-compose-foot">
                  <div className="mp-compose-left">
                    <button
                      type="button"
                      onClick={() => fileRef.current?.click()}
                    >
                      加照片
                    </button>
                    <button
                      type="button"
                      onClick={() => toggleVoice(false)}
                    >
                      {recording ? "结束听写" : "语音听写"}
                    </button>
                  </div>
                  <button
                    type="button"
                    className="mp-send-btn"
                    disabled={!!busy || !(text.trim() || asset)}
                    onClick={() => send()}
                  >
                    发送
                  </button>
                </div>
              </div>

              {callMode && (
                <div className="mp-live-call">
                  <div>
                    <b>连续语音对话</b>
                    <small>{recording ? "正在听…" : "点按钮继续说话"}</small>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      setCallMode(false);
                      setRecording(false);
                      speechRef.current?.abort();
                    }}
                  >
                    结束通话
                  </button>
                </div>
              )}
              {error && <p className="mp-error">{error}</p>}
            </div>
          )}

          {tab === "works" && (
            <div className="mp-list-page">
              {data.works.length === 0 ? (
                <p className="mp-empty-box">还没有成品，回「创作」发一句话试试。</p>
              ) : (
                data.works.map((w) => (
                  <a
                    key={w.id}
                    href={"#work/" + w.id}
                    className="mp-work-item"
                  >
                    {w.preview && <img src={w.preview} alt={w.title} />}
                    <div>
                      <b>{w.title}</b>
                      <small>
                        {w.kind === "video"
                          ? "宣传短片"
                          : w.kind === "copy"
                            ? "推广文案"
                            : "营销海报"}
                      </small>
                    </div>
                    <ChevronRight size={16} />
                  </a>
                ))
              )}
            </div>
          )}

          {tab === "mine" && (
            <div className="mp-list-page">
              <div className="mp-mine-card">
                <div>
                  <b>{data.profile.name || "我的小店"}</b>
                  <small>{data.profile.industry || "未设置行业"}</small>
                </div>
                <button
                  type="button"
                  className="pa-credit-pill"
                  onClick={onOpenCredits}
                >
                  <Zap size={13} fill="currentColor" />
                  {data.credits} 积分
                </button>
              </div>
              <button
                type="button"
                className="mp-menu-row"
                onClick={() => setShowMemory(true)}
              >
                <span>助理记忆与周推荐</span>
                <ChevronRight size={16} />
              </button>
              <button
                type="button"
                className="mp-menu-row"
                onClick={onOpenCredits}
              >
                <span>套餐与积分余额</span>
                <ChevronRight size={16} />
              </button>
              <button
                type="button"
                className="mp-menu-row"
                onClick={() => onGo("profile")}
              >
                <span>店铺资料与行业标签</span>
                <ChevronRight size={16} />
              </button>
              <button
                type="button"
                className="mp-menu-row"
                onClick={onOpenAccount}
              >
                <span>账号登录与同步</span>
                <ChevronRight size={16} />
              </button>
              <button
                type="button"
                className="mp-menu-row"
                onClick={() => onGo("home")}
              >
                <span>切换到桌面网页版</span>
                <ChevronRight size={16} />
              </button>
            </div>
          )}
        </div>

        {/* Authentic WeChat Bottom Tab Bar */}
        {!(tab === "home" && screen === "chat") && (
          <nav className="mp-tabbar" aria-label="小程序底部导航">
            <button
              type="button"
              className={tab === "home" ? "active" : ""}
              onClick={() => {
                setTab("home");
                setScreen("home");
              }}
            >
              <Home size={20} />
              <span>创作</span>
            </button>
            <button
              type="button"
              className={tab === "works" ? "active" : ""}
              onClick={() => setTab("works")}
            >
              <Images size={20} />
              <span>作品</span>
            </button>
            <button
              type="button"
              className={tab === "mine" ? "active" : ""}
              onClick={() => setTab("mine")}
            >
              <User size={20} />
              <span>我的</span>
            </button>
          </nav>
        )}
      </div>

      {showMemory && (
        <AgentMemory
          conversationId={chat?.id}
          project={chat?.project}
          assets={data.assets}
          weeks={home.weeks}
          onWeeks={(weeks) => setHome((h) => ({ ...h, weeks }))}
          onChanged={() => {
            syncHome();
            if (chat?.id) api(root + "/" + chat.id).then(setChat).catch(() => {});
          }}
          onClose={() => setShowMemory(false)}
        />
      )}
    </div>
  );
}
