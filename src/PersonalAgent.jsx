import React, { useEffect, useRef, useState } from "react";
import {
  ArrowUp,
  BookOpen,
  Check,
  ChevronRight,
  Compass,
  FolderKanban,
  ImagePlus,
  Images,
  LoaderCircle,
  Menu,
  MessageSquare,
  Mic,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Settings2,
  SlidersHorizontal,
  Sparkles,
  Square,
  Store,
  X,
  Zap,
} from "lucide-react";
import { api, Modal } from "./ui.jsx";
import { RatioPicker, shapes } from "./CreationSpecs.jsx";
import ProductRegion from "./ProductRegion.jsx";
import AgentTask, { kinds, states } from "./AgentTask.jsx";
import AgentMemory from "./AgentMemory.jsx";
import "./agent.css";

const root = "/agent/conversations";
const activeStates = ["planning", "queued", "running", "reviewing"];
const choiceKey = () =>
  globalThis.crypto?.randomUUID?.() ||
  Date.now().toString(36) + Math.random().toString(36).slice(2);

const quickPrompts = [
  { label: "做张周末促销海报", kind: "poster", seed: "想做一张周末促销海报，主打" },
  { label: "写条新品朋友圈", kind: "copy", seed: "想写一条新品朋友圈文案，介绍" },
  { label: "剪个15秒揽客短片", kind: "video", seed: "想做一条15秒揽客短片，介绍" },
  { label: "看看本周灵感", action: "topics" },
];

function greetingText(shopName) {
  const hour = new Date().getHours();
  const timeWord =
    hour < 11 ? "早上好" : hour < 14 ? "中午好" : hour < 18 ? "下午好" : "晚上好";
  return shopName
    ? `${timeWord}，今天想为${shopName}推什么？`
    : `${timeWord}，今天想推广什么？`;
}

export default function PersonalAgent({
  data,
  refresh,
  tip,
  seed,
  clearSeed,
  onGo,
  onOpenCredits,
  onOpenAccount,
  onOpenAdmin,
}) {
  const [home, setHome] = useState({
      conversations: [],
      projects: [],
      weeks: 1,
      pending: null,
      candidateCount: 0,
    }),
    [chat, setChat] = useState(null);
  const [writing, setWriting] = useState({}),
    [writingErrors, setWritingErrors] = useState({});
  const [input, setInput] = useState(""),
    [options, setOptions] = useState({}),
    [target, setTarget] = useState(null);
  const [panel, setPanel] = useState(""),
    [busy, setBusy] = useState(""),
    [ready, setReady] = useState(false),
    [error, setError] = useState("");
  const [railOpen, setRailOpen] = useState(false),
    [railCollapsed, setRailCollapsed] = useState(false);
  const [workRef, setWorkRef] = useState(null),
    [project, setProject] = useState(""),
    [projectTitle, setProjectTitle] = useState(""),
    [recording, setRecording] = useState(false);
  const [assetRights, setAssetRights] = useState(
    () => sessionStorage.getItem("trupic.assetRights") === "1",
  );
  const textarea = useRef(null),
    file = useRef(null),
    live = useRef(true),
    current = useRef(null),
    generation = useRef(0),
    lock = useRef(false),
    speech = useRef(null),
    recorder = useRef(null),
    end = useRef(null);
  const storage = "trupic.agent." + data.workspace;
  const speechApi = window.SpeechRecognition || window.webkitSpeechRecognition;
  const canRecord =
    !!speechApi ||
    (!!navigator.mediaDevices?.getUserMedia &&
      typeof MediaRecorder !== "undefined");
  const asset = data.assets.find((a) => a.id === options.asset);
  const projectName = home.projects.find(
    (p) => p.id === (chat?.project || project),
  )?.title;
  const task = chat?.tasks.find((t) => t.id === target);
  const change = (v) => setOptions((o) => ({ ...o, ...v }));
  const confirmRights = (checked) => {
    setAssetRights(checked);
    try {
      sessionStorage.setItem("trupic.assetRights", checked ? "1" : "0");
    } catch {}
  };
  const syncHome = async () => {
    const h = await api("/agent");
    if (live.current) setHome(h);
    return h;
  };
  function display(c) {
    current.current = c?.id || null;
    setChat(c);
    if (c) sessionStorage.setItem(storage, c.id);
    else sessionStorage.removeItem(storage);
  }
  function stopAudio() {
    speech.current?.abort();
    if (recorder.current?.state === "recording") {
      try {
        recorder.current.stop();
      } catch {}
    }
    setRecording(false);
  }
  function reset() {
    setInput("");
    setOptions({});
    setTarget(null);
    setWorkRef(null);
    setPanel("");
    setError("");
    stopAudio();
  }
  async function openChat(id) {
    const version = ++generation.current;
    const c = await api(root + "/" + id + "/visit", "POST", {});
    if (live.current && version === generation.current) {
      reset();
      setRailOpen(false);
      setProject(c.project || "");
      display(c);
    }
  }
  useEffect(() => {
    live.current = true;
    (async () => {
      const h = await syncHome();
      const stored = sessionStorage.getItem(storage);
      const id = h.conversations.find((c) => c.id === stored)?.id;
      if (id && live.current) await openChat(id);
      if (live.current) setReady(true);
    })().catch((e) => {
      if (live.current) setError(e.message);
    });
    return () => {
      live.current = false;
      generation.current++;
      stopAudio();
    };
  }, [storage]);
  useEffect(() => {
    if (!ready || !seed || seed.workspace !== data.workspace) return;
    generation.current++;
    reset();
    display(null);
    setProject("");
    setOptions(seed.options);
    setInput(seed.brief);
    clearSeed();
    textarea.current?.focus();
  }, [seed, ready, data.workspace]);

  async function perform(label, fn) {
    if (lock.current) return;
    lock.current = true;
    generation.current++;
    setBusy(label);
    setError("");
    try {
      await fn();
    } catch (e) {
      if (live.current) setError(e.message);
    } finally {
      lock.current = false;
      if (live.current) setBusy("");
    }
  }
  const chatId = chat?.id;
  const running = (chat?.tasks || []).filter((t) =>
    activeStates.includes(t.status),
  );
  const runningKey = running.map((t) => t.id).join(",");
  useEffect(() => {
    if (!chatId) return;
    let alive = true,
      timer;
    const cursors = new Map();
    async function poll(focusEvent) {
      const version = generation.current;
      if (!alive || document.hidden || lock.current) return;
      try {
        const updates = new Map();
        if (runningKey && !focusEvent) {
          await Promise.all(
            runningKey.split(",").map(async (id) => {
              const r = await api(
                "/agent/tasks/" +
                  id +
                  "/events?after=" +
                  (cursors.get(id) || 0),
              );
              if (r.events.length) cursors.set(id, r.events.at(-1).seq);
              updates.set(id, r.task);
            }),
          );
        }
        const snapshot = updates.size ? null : await api(root + "/" + chatId);
        if (
          !alive ||
          current.current !== chatId ||
          generation.current !== version ||
          lock.current
        )
          return;
        if (snapshot) setChat(snapshot);
        else
          setChat((c) =>
            c?.id === chatId
              ? { ...c, tasks: c.tasks.map((t) => updates.get(t.id) || t) }
              : c,
          );
        if ([...updates.values()].some((t) => !activeStates.includes(t.status))) {
          await refresh();
          await syncHome();
        }
      } catch (e) {
        if (alive && current.current === chatId) setError(e.message);
      }
    }
    async function tick() {
      await poll();
      if (alive) timer = setTimeout(tick, runningKey ? 2000 : 14000);
    }
    timer = setTimeout(tick, runningKey ? 1200 : 14000);
    window.addEventListener("focus", poll);
    return () => {
      alive = false;
      clearTimeout(timer);
      window.removeEventListener("focus", poll);
    };
  }, [chatId, runningKey]);

  async function create(pid) {
    const c = await api(root, "POST", { project: pid || null });
    if (live.current) {
      display(c);
      await syncHome();
    }
    return c;
  }
  function startFresh(pid = "") {
    generation.current++;
    reset();
    display(null);
    setRailOpen(false);
    setProject(pid);
    requestAnimationFrame(() => textarea.current?.focus());
  }
  function scroll() {
    requestAnimationFrame(() =>
      end.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }),
    );
  }
  async function send(text, extra = {}, providedOptions = options) {
    if (!text.trim()) return;
    await perform("send", async () => {
      const c = chat || (await create(project));
      const body = {
        text: text.trim(),
        options: providedOptions,
        ...(workRef ? { workRef, action: "new" } : {}),
        ...extra,
      };
      if (task && !extra.action)
        Object.assign(body, {
          action: "revise",
          task: task.id,
          revision: task.revision,
        });
      else if (!extra.action && c.tasks.length) {
        const latest = c.tasks.at(-1);
        Object.assign(body, { task: latest.id, revision: latest.revision });
      }
      const key = storage + ".send." + c.id;
      const signature = JSON.stringify(body);
      let last = JSON.parse(sessionStorage.getItem(key) || "null");
      if (last?.signature !== signature) {
        last = { signature, key: choiceKey() };
        sessionStorage.setItem(key, JSON.stringify(last));
      }
      const answer = await api(root + "/" + c.id + "/messages", "POST", {
        ...body,
        requestKey: last.key,
      });
      sessionStorage.removeItem(key);
      if (!live.current) return;
      reset();
      display(answer);
      await syncHome();
      scroll();
      const latest = answer.tasks.at(-1);
      if (
        (latest?.status === "waiting_copy" ||
          latest?.status === "waiting_script") &&
        !latest.options.length
      ) {
        generateOptions(answer.id, latest);
      }
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
      if (live.current && current.current === cid) {
        generation.current++;
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
  async function action(t, verb, job, option = 0) {
    if (verb === "options") return generateOptions(chat.id, t);
    await perform(verb, async () => {
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
      if (live.current) display(await api(root + "/" + chat.id));
      await syncHome();
      await refresh();
    });
  }
  async function decideCandidate(cand, accept) {
    await perform("memory", async () => {
      await api(
        "/agent/memory/" + cand.id + (accept ? "/confirm" : "/dismiss"),
        "POST",
        { version: cand.version },
      );
      if (live.current && chat) display(await api(root + "/" + chat.id));
      await syncHome();
      tip(accept ? `已记住「${cand.name}」` : "已忽略该条建议");
    });
  }
  function edit(t, copy) {
    setTarget(t.id);
    setInput("");
    setOptions(t.asset ? { asset: t.asset } : {});
    setPanel(copy ? "own" : "");
    setError("");
    requestAnimationFrame(() => {
      textarea.current?.focus();
      end.current?.scrollIntoView({ block: "end" });
    });
  }
  async function upload(e) {
    const files = Array.from(e.target.files || []);
    e.target.value = "";
    if (!files.length) return;
    await perform("upload", async () => {
      if (files.length > 3) throw new Error("一次最多选择三张照片。");
      confirmRights(true);
      const uploaded = [];
      for (const f of files) {
        const form = new FormData();
        form.append("image", f);
        uploaded.push(await api("/assets", "POST", form));
      }
      const selected =
        uploaded.length === 1
          ? { asset: uploaded[0].id, references: [] }
          : await api("/assets/suggest-sources", "POST", {
              ids: uploaded.map((a) => a.id),
              brief: input,
              authorized: true,
            });
      change({
        asset: selected.asset,
        references: selected.references,
        assetMode: "original",
        identityRegion: null,
        assetConfirmed: false,
      });
      await refresh();
      tip("照片已添加");
    });
  }
  async function voice() {
    if (recording) {
      if (speech.current) speech.current.stop();
      if (recorder.current?.state === "recording") recorder.current.stop();
      setRecording(false);
      return;
    }
    if (speechApi) {
      const rec = new speechApi();
      speech.current = rec;
      rec.lang = "zh-CN";
      rec.onresult = (e) =>
        setInput((v) => (v + e.results[0][0].transcript).slice(0, 1200));
      rec.onend = () => setRecording(false);
      rec.onerror = () => setError("语音输入未完成，可再次录音或输入文字。");
      try {
        rec.start();
        setRecording(true);
      } catch {
        setError("无法开启麦克风。");
      }
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const chunks = [];
      const mr = new MediaRecorder(stream);
      recorder.current = mr;
      mr.ondataavailable = (ev) => {
        if (ev.data.size > 0) chunks.push(ev.data);
      };
      mr.onstop = async () => {
        stream.getTracks().forEach((tr) => tr.stop());
        if (!chunks.length) return;
        await perform("voice", async () => {
          const blob = new Blob(chunks, { type: mr.mimeType || "audio/webm" });
          const form = new FormData();
          form.append("audio", blob, "speech.webm");
          const res = await api("/voice/transcribe", "POST", form);
          if (res.text)
            setInput((v) => (v ? v + " " + res.text : res.text).slice(0, 1200));
        });
      };
      mr.start();
      setRecording(true);
    } catch {
      setError("无法开启麦克风，请改用文字输入。");
    }
  }

  const messages = chat?.messages || [];
  const latestCard = new Map(
    messages.filter((m) => m.kind === "task").map((m) => [m.task, m.seq]),
  );
  const cards = new Map((chat?.tasks || []).map((t) => [t.id, t]));
  const showWelcome = !messages.some((m) => m.role === "user") && !messages.length;
  const activeKind = options.kind || task?.kind || "poster";
  const activeRatio =
    options.ratio ||
    task?.ratio ||
    (activeKind === "video" ? "story" : "portrait");
  const specBadge =
    activeKind === "copy"
      ? "纯文案"
      : activeKind === "video"
        ? `${shapes[activeRatio]} · ${options.duration || task?.duration || 15}秒`
        : `${shapes[activeRatio]} · ${options.imageCount || task?.imageCount || 1}张`;
  const pendingCandidate = chat?.candidates?.[0] || null;
  const candidateTotal = Math.max(
    home.candidateCount || 0,
    chat?.candidates?.length || 0,
  );

  const composerEl = (
    <form
      className={"pa-composer " + (showWelcome ? "hero" : "")}
      onSubmit={(e) => {
        e.preventDefault();
        send(
          input ||
            (options.ownCopy
              ? "使用我的文案"
              : options.asset
                ? "用这张商品图做一张海报"
                : ""),
        );
      }}
    >
      {(workRef || task || options.asset || options.kind || options.ownCopy) && (
        <div className="agent-attachments">
          {workRef && (
            <span>
              沿用 · {workRef.label}
              <button
                type="button"
                aria-label="清除作品引用"
                onClick={() => setWorkRef(null)}
              >
                <X size={12} />
              </button>
            </span>
          )}
          {task && (
            <span>
              修改 · {kinds[task.kind]}
              <button
                type="button"
                aria-label="退出修改"
                onClick={() => setTarget(null)}
              >
                <X size={12} />
              </button>
            </span>
          )}
          {asset && (
            <span>
              <img
                src={asset.original}
                alt=""
                onClick={() => setPanel("asset")}
                style={{ cursor: "pointer" }}
              />
              <button
                type="button"
                onClick={() => setPanel("asset")}
                title="核对包装标识"
              >
                {asset.name}
              </button>
              <button
                type="button"
                aria-label="移除素材"
                onClick={() =>
                  change({
                    asset: "",
                    references: [],
                    identityRegion: null,
                    assetConfirmed: false,
                  })
                }
              >
                <X size={12} />
              </button>
            </span>
          )}
          {options.kind && <span>{kinds[options.kind]}</span>}
          {options.ownCopy && <span>已附文案</span>}
        </div>
      )}

      <textarea
        ref={textarea}
        aria-label="给营销助理发消息"
        maxLength={1200}
        rows={showWelcome ? 3 : 2}
        placeholder={
          task
            ? "想改哪里？比如「把19元改为29元」或「换横版」"
            : showWelcome
              ? "说说店里要推什么，或丢张商品图进来…"
              : "继续告诉助理，或说「记住：…」"
        }
        value={input}
        disabled={!!busy || !ready}
        onChange={(e) => {
          setInput(e.target.value);
          if (options.topicId) change({ topicId: "", source: "对话创作" });
        }}
        onKeyDown={(e) => {
          if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
            e.preventDefault();
            send(input);
          }
        }}
      />

      <input
        type="file"
        multiple
        accept="image/jpeg,image/png,image/webp"
        aria-label="选择商品照片"
        ref={file}
        hidden
        onChange={upload}
      />

      <div className="pa-composer-bar">
        <div className="pa-composer-left">
          <button
            type="button"
            className="pa-tool-btn"
            disabled={!!busy}
            onClick={() => {
              if (assetRights) file.current?.click();
              else setPanel("asset");
            }}
          >
            <ImagePlus size={17} />
            <span>{asset ? "换图" : "发图"}</span>
          </button>
          <button
            type="button"
            className="pa-tool-btn spec"
            disabled={!!busy}
            onClick={() => setPanel("spec")}
          >
            <SlidersHorizontal size={14} />
            <span>{specBadge}</span>
          </button>
        </div>
        <div className="pa-composer-right">
          {canRecord && (
            <button
              type="button"
              className={"pa-mic-btn " + (recording ? "recording" : "")}
              disabled={!!busy}
              aria-label={recording ? "结束录音" : "说话输入"}
              aria-pressed={recording}
              onClick={voice}
            >
              {recording ? <Square size={15} /> : <Mic size={16} />}
              <span>{recording ? "说完了" : "说需求"}</span>
            </button>
          )}
          <button
            className="pa-send-btn"
            aria-label="发送消息"
            disabled={
              !!busy ||
              !ready ||
              !(input.trim() || options.ownCopy || options.asset)
            }
          >
            {busy === "send" ? (
              <LoaderCircle size={18} className="spin" />
            ) : (
              <ArrowUp size={19} />
            )}
          </button>
        </div>
      </div>
    </form>
  );

  const topicCards = (m) => (
    <div className="agent-topics">
      <h3>本周可以做什么</h3>
      {m.items.map((r, i) => (
        <button
          key={r.topicId}
          disabled={!!busy}
          onClick={() =>
            send(r.brief, { action: "new" }, { topicId: r.topicId })
          }
        >
          <span>{i + 1}.</span>
          {r.title}
          <ChevronRight size={15} />
        </button>
      ))}
    </div>
  );

  return (
    <div className={"pa-shell " + (railCollapsed ? "rail-collapsed" : "")}>
      {railOpen && (
        <div
          className="pa-backdrop"
          onClick={() => setRailOpen(false)}
          aria-hidden="true"
        />
      )}

      <aside
        className={"pa-rail " + (railOpen ? "open" : "")}
        aria-label="对话与助理空间"
      >
        <div className="pa-rail-top">
          <button
            type="button"
            className="pa-brand"
            onClick={() => startFresh("")}
          >
            <img src="/favicon.svg" alt="" />
            <span>
              <b>响指出片</b>
              <small>营销助理</small>
            </span>
          </button>
          <button
            type="button"
            className="pa-icon-btn desktop-only"
            aria-label="收起侧栏"
            onClick={() => setRailCollapsed(true)}
          >
            <PanelLeftClose size={18} />
          </button>
          <button
            type="button"
            className="pa-icon-btn mobile-only"
            aria-label="关闭侧栏"
            onClick={() => setRailOpen(false)}
          >
            <X size={18} />
          </button>
        </div>

        <button
          type="button"
          className="pa-new-btn"
          disabled={!!busy || !ready}
          onClick={() => startFresh("")}
        >
          <Plus size={17} />
          <span>新对话</span>
        </button>

        <div className="pa-rail-scroll">
          <div className="pa-rail-section">
            <div className="pa-section-head">
              <span>营销项目</span>
              <button
                type="button"
                onClick={() => {
                  setProject("+");
                  setPanel("project");
                }}
                title="新建活动项目"
              >
                <Plus size={14} />
              </button>
            </div>
            {home.projects.length === 0 ? (
              <button
                type="button"
                className="pa-rail-muted"
                onClick={() => {
                  setProject("+");
                  setPanel("project");
                }}
              >
                <FolderKanban size={15} />
                按活动建项目，价格不串用
              </button>
            ) : (
              home.projects.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  className={
                    "pa-rail-item " +
                    ((chat?.project || project) === p.id ? "active" : "")
                  }
                  onClick={() => startFresh(p.id)}
                >
                  <FolderKanban size={15} />
                  <span>{p.title}</span>
                </button>
              ))
            )}
          </div>

          <div className="pa-rail-section">
            <div className="pa-section-head">
              <span>最近对话</span>
            </div>
            {home.conversations.length === 0 && (
              <p className="pa-rail-empty">发第一句话后会自动保存</p>
            )}
            {home.conversations.map((c) => {
              const pTitle = home.projects.find((p) => p.id === c.project)?.title;
              return (
                <div
                  key={c.id}
                  className={"pa-chat-row " + (c.id === chat?.id ? "active" : "")}
                >
                  <button
                    type="button"
                    aria-current={c.id === chat?.id}
                    onClick={() => perform("open", () => openChat(c.id))}
                  >
                    <MessageSquare size={15} />
                    <span className="pa-chat-meta">
                      <b>{c.title}</b>
                      {(c.activeStatus || pTitle) && (
                        <small>
                          {c.activeStatus && (
                            <i className="pa-live-dot" title={states[c.activeStatus]} />
                          )}
                          {c.activeStatus ? states[c.activeStatus] : pTitle}
                        </small>
                      )}
                    </span>
                  </button>
                  <button
                    type="button"
                    className="pa-chat-del"
                    aria-label={"移除对话 " + c.title}
                    title="移除对话（后台制作继续）"
                    disabled={!!busy}
                    onClick={() =>
                      perform("archive", async () => {
                        await api(root + "/" + c.id, "DELETE");
                        const h = await syncHome();
                        if (c.id === chat?.id) {
                          if (h.conversations[0])
                            await openChat(h.conversations[0].id);
                          else startFresh("");
                        }
                      })
                    }
                  >
                    <X size={14} />
                  </button>
                </div>
              );
            })}
          </div>
        </div>

        <div className="pa-rail-footer">
          <button
            type="button"
            className="pa-rail-item"
            onClick={() => {
              setRailOpen(false);
              setPanel("memory");
            }}
          >
            <BookOpen size={16} />
            <span>助理记忆</span>
            {candidateTotal > 0 && (
              <em className="pa-count-pill">{candidateTotal}</em>
            )}
          </button>
          <button
            type="button"
            className="pa-rail-item"
            onClick={() => {
              setRailOpen(false);
              onGo("works");
            }}
          >
            <Images size={16} />
            <span>我的作品</span>
            {data.works.length > 0 && <small>{data.works.length}</small>}
          </button>
          <button
            type="button"
            className="pa-rail-item"
            onClick={() => {
              setRailOpen(false);
              onGo("profile");
            }}
          >
            <Store size={16} />
            <span>店铺档案</span>
          </button>

          <div className="pa-rail-sublinks">
            <button type="button" onClick={() => { setRailOpen(false); onGo("mp"); }}>
              小程序版
            </button>
            <button type="button" onClick={() => { setRailOpen(false); onGo("inspiration"); }}>
              <Compass size={13} />灵感
            </button>
            <button type="button" onClick={() => { setRailOpen(false); onGo("studio"); }}>
              原创作台
            </button>
            <button type="button" onClick={() => { setRailOpen(false); onOpenAdmin(); }}>
              <Settings2 size={13} />后台
            </button>
          </div>

          <div className="pa-account-strip">
            <button
              type="button"
              className="pa-account-btn"
              onClick={() => {
                setRailOpen(false);
                onOpenAccount();
              }}
            >
              <span className="pa-avatar">
                {(data.profile.name || "店").slice(0, 1)}
              </span>
              <span>
                <b>{data.profile.name || "我的小店"}</b>
                <small>{data.login || "点击登录 / 同步"}</small>
              </span>
            </button>
            <button
              type="button"
              className="pa-credit-pill"
              onClick={() => {
                setRailOpen(false);
                onOpenCredits();
              }}
            >
              <Zap size={13} fill="currentColor" />
              {data.credits}
            </button>
          </div>
        </div>
      </aside>

      <section className="pa-stage">
        <header className="pa-topbar">
          <div className="pa-topbar-left">
            <button
              type="button"
              className="pa-icon-btn mobile-only"
              aria-label="打开对话列表"
              onClick={() => {
                syncHome().catch(() => {});
                setRailOpen(true);
              }}
            >
              <Menu size={20} />
            </button>
            {railCollapsed && (
              <button
                type="button"
                className="pa-icon-btn desktop-only"
                aria-label="展开侧栏"
                onClick={() => setRailCollapsed(false)}
              >
                <PanelLeftOpen size={18} />
              </button>
            )}
            <div className="pa-topbar-title">
              <strong>{showWelcome ? "营销助理" : chat?.title || "营销助理"}</strong>
              {projectName && (
                <button
                  type="button"
                  className="pa-project-tag"
                  onClick={() => setPanel("project")}
                >
                  {projectName}
                </button>
              )}
            </div>
          </div>

          <div className="pa-topbar-right">
            <button
              type="button"
              className="pa-top-memory"
              onClick={() => setPanel("memory")}
              aria-label="助理记忆"
              title="查看或编辑助理记忆"
            >
              <BookOpen size={16} />
              <span className="desktop-only">记忆</span>
              {candidateTotal > 0 && <i className="agent-dot" />}
            </button>
            <button
              type="button"
              className="pa-credit-pill mobile-only"
              onClick={onOpenCredits}
            >
              <Zap size={13} fill="currentColor" />
              {data.credits}
            </button>
            {!showWelcome && (
              <button
                type="button"
                className="pa-icon-btn"
                aria-label="新对话"
                title="新对话"
                disabled={!!busy || !ready}
                onClick={() => startFresh("")}
              >
                <Plus size={19} />
              </button>
            )}
          </div>
        </header>

        {showWelcome ? (
          <div className="pa-welcome-wrap">
            <div className="pa-welcome-inner">
              <div className="pa-emblem">
                <img src="/favicon.svg" alt="" />
              </div>
              <h1>{greetingText(data.profile.name)}</h1>
              <p className="pa-welcome-sub">
                直接说话、打字或发张商品图，文案、海报和短片我来帮你一起搞定。
              </p>

              {composerEl}

              {busy && (
                <p className="agent-feedback" role="status">
                  {busy === "send"
                    ? "正在梳理你的需求…"
                    : busy === "upload"
                      ? "正在上传照片…"
                      : busy === "voice"
                        ? "正在把语音转成文字…"
                        : "正在处理…"}
                </p>
              )}
              {error && (
                <p className="error" role="alert">
                  {error}{" "}
                  {!ready && (
                    <button onClick={() => location.reload()}>重新连接</button>
                  )}
                </p>
              )}

              <div className="pa-prompt-chips">
                {quickPrompts.map((q) => (
                  <button
                    key={q.label}
                    type="button"
                    disabled={!!busy || !ready}
                    onClick={() => {
                      if (q.action === "topics") {
                        send("本周推荐", { action: "topics" }, {});
                      } else {
                        setInput(q.seed);
                        setOptions({ kind: q.kind });
                        textarea.current?.focus();
                      }
                    }}
                  >
                    <Sparkles size={13} />
                    {q.label}
                  </button>
                ))}
              </div>

              {home.pending && (
                <button
                  type="button"
                  className="pa-resume-card"
                  disabled={!!busy}
                  onClick={() =>
                    perform("open", () => openChat(home.pending.conversation))
                  }
                >
                  <div className="pa-resume-top">
                    <span>
                      <i className="pa-resume-dot" />
                      接着做 · {states[home.pending.status] || "进行中"}
                    </span>
                    {home.pending.cost != null && (
                      <b>{home.pending.cost} 积分</b>
                    )}
                  </div>
                  <div className="pa-resume-bottom">
                    <span>{home.pending.title || "未完成的创作任务"}</span>
                    <em>
                      继续处理 <ChevronRight size={15} />
                    </em>
                  </div>
                </button>
              )}
            </div>
          </div>
        ) : (
          <>
            <div className="pa-thread-scroll">
              <div className="pa-thread">
                {messages.map((m) => {
                  if (m.kind === "task") {
                    if (latestCard.get(m.task) !== m.seq) return null;
                    const t = cards.get(m.task);
                    return (
                      t && (
                        <div className="pa-turn assistant" key={m.seq}>
                          <div className="pa-turn-mark">
                            <img src="/favicon.svg" alt="" />
                          </div>
                          <div className="pa-turn-body">
                            <AgentTask
                              writing={writing[t.id] === t.revision}
                              writingError={
                                writingErrors[t.id]?.revision === t.revision
                                  ? writingErrors[t.id].message
                                  : ""
                              }
                              onOpenMemory={() => setPanel("memory")}
                              {...{ task: t, busy: !!busy, action, send, edit, tip }}
                            />
                          </div>
                        </div>
                      )
                    );
                  }
                  if (m.kind === "topics")
                    return (
                      <div className="pa-turn assistant" key={m.seq}>
                        <div className="pa-turn-mark">
                          <img src="/favicon.svg" alt="" />
                        </div>
                        <div className="pa-turn-body">{topicCards(m)}</div>
                      </div>
                    );
                  if (m.kind === "pick_work")
                    return (
                      <div className="pa-turn assistant" key={m.seq}>
                        <div className="pa-turn-mark">
                          <img src="/favicon.svg" alt="" />
                        </div>
                        <div className="pa-turn-body">
                          <div className="pa-prose">{m.text}</div>
                          <div className="agent-links">
                            {m.items.map((w) => (
                              <button
                                className="pa-inline-chip"
                                disabled={!!busy}
                                key={w.id}
                                onClick={() => {
                                  if (m.needsInstruction) {
                                    setWorkRef(w);
                                    setInput("照这个再做，");
                                    textarea.current?.focus();
                                  } else
                                    send(
                                      m.instruction,
                                      { action: "new", workRef: w },
                                      {},
                                    );
                                }}
                              >
                                {w.label}
                              </button>
                            ))}
                          </div>
                        </div>
                      </div>
                    );
                  if (m.kind === "switch")
                    return (
                      <div className="pa-turn assistant" key={m.seq}>
                        <div className="pa-turn-mark">
                          <img src="/favicon.svg" alt="" />
                        </div>
                        <div className="pa-turn-body">
                          <div className="pa-prose">
                            这像是一个新任务，要另开对话避免和当前任务混淆吗？
                          </div>
                          <div className="agent-links">
                            <button
                              className="agent-chip-primary"
                              disabled={!!busy}
                              onClick={() =>
                                send(m.text, { action: "branch" }, m.options)
                              }
                            >
                              另开新对话（推荐）
                            </button>
                            <button
                              className="pa-inline-chip"
                              disabled={!!busy}
                              onClick={() =>
                                send(m.text, { action: "here" }, m.options)
                              }
                            >
                              留在这里继续
                            </button>
                          </div>
                        </div>
                      </div>
                    );
                  if (m.role === "user")
                    return (
                      <div className="pa-turn user" key={m.seq}>
                        <div className="pa-user-bubble">
                          {m.asset && (
                            <img
                              className="agent-source-photo"
                              src={"/api/assets/" + m.asset + "/original"}
                              alt="本条消息的商品照片"
                            />
                          )}
                          <div>{m.text}</div>
                        </div>
                      </div>
                    );
                  return (
                    <div className="pa-turn assistant" key={m.seq}>
                      <div className="pa-turn-mark">
                        <img src="/favicon.svg" alt="" />
                      </div>
                      <div className="pa-turn-body">
                        <div className="pa-prose">{m.text}</div>
                        {m.recalled?.length > 0 && (
                          <button
                            type="button"
                            className="agent-bubble-recalled"
                            onClick={() => setPanel("memory")}
                          >
                            <BookOpen size={11} />
                            已参考记忆：{m.recalled.map((r) => r.name).join("、")}
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
                <div ref={end} />
              </div>
            </div>

            <div className="pa-dock">
              <div className="pa-dock-inner">
                {pendingCandidate && (
                  <div className="agent-candidate-bar" role="status">
                    <span>
                      <Sparkles size={14} />
                      需要长期记住吗？<b>{pendingCandidate.name}</b>：
                      {pendingCandidate.value}
                    </span>
                    <div>
                      <button
                        type="button"
                        className="agent-chip-primary"
                        disabled={!!busy}
                        onClick={() => decideCandidate(pendingCandidate, true)}
                      >
                        记住
                      </button>
                      <button
                        type="button"
                        disabled={!!busy}
                        onClick={() => decideCandidate(pendingCandidate, false)}
                      >
                        不用
                      </button>
                    </div>
                  </div>
                )}
                {busy && (
                  <p className="agent-feedback" role="status">
                    {busy === "send"
                      ? "助理正在整理…"
                      : busy === "upload"
                        ? "正在上传照片…"
                        : busy === "voice"
                          ? "正在把语音转成文字…"
                          : "正在处理…"}
                  </p>
                )}
                {error && (
                  <p className="error" role="alert">
                    {error}
                  </p>
                )}
                {composerEl}
              </div>
            </div>
          </>
        )}
      </section>

      {panel === "project" && (
        <Modal title="营销项目" onClose={() => setPanel("")}>
          <div className="agent-fields">
            <p className="agent-hint-text">
              同一项目下的对话共享活动价格与资料，不同活动互不串用。
            </p>
            <label>
              选择或新建项目
              <select
                value={project}
                onChange={(e) => setProject(e.target.value)}
              >
                <option value="">独立对话（仅用店铺长期记忆）</option>
                {home.projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.title}
                  </option>
                ))}
                <option value="+">+ 新建项目…</option>
              </select>
            </label>
            {project === "+" && (
              <input
                aria-label="项目名称"
                maxLength={60}
                placeholder="例如：周末满减活动、春季上新"
                value={projectTitle}
                onChange={(e) => setProjectTitle(e.target.value)}
              />
            )}
            <button
              className="primary"
              disabled={!!busy || (project === "+" && !projectTitle.trim())}
              onClick={() =>
                perform("new", async () => {
                  let pid = project;
                  if (pid === "+")
                    pid = (
                      await api("/agent/projects", "POST", {
                        title: projectTitle,
                      })
                    ).id;
                  await create(pid);
                  reset();
                  setRailOpen(false);
                  setProject(pid);
                  setProjectTitle("");
                  textarea.current?.focus();
                })
              }
            >
              进入该项目对话
            </button>
          </div>
        </Modal>
      )}

      {panel === "asset" && (
        <Modal title="商品实拍与参考素材" onClose={() => setPanel("")}>
          <div className="agent-fields">
            <label className="agent-check-row">
              <input
                type="checkbox"
                checked={assetRights}
                onChange={(e) => confirmRights(e.target.checked)}
              />
              <span>我有权使用所选商品照片或参考素材</span>
            </label>
            <button
              className="primary"
              disabled={!!busy || !assetRights}
              onClick={() => file.current.click()}
            >
              <ImagePlus size={16} />
              从相册选择照片（最多三张）
            </button>
            <label>
              视频节奏参考（选填）
              <input
                type="file"
                accept="video/mp4,video/quicktime"
                disabled={!assetRights || !!busy}
                onChange={(e) => {
                  const f = e.target.files[0];
                  e.target.value = "";
                  if (!f) return;
                  perform("upload", async () => {
                    const form = new FormData();
                    form.append("video", f);
                    form.append("authorized", "true");
                    const clip = await api("/video-references", "POST", form);
                    change({ kind: "video", videoReference: clip.id });
                  });
                }}
              />
            </label>
            {options.videoReference && <small>已添加视频节奏参考</small>}
            {data.assets.length > 0 && (
              <label>
                或从素材库选用
                <select
                  disabled={!assetRights}
                  value={options.asset || ""}
                  onChange={(e) =>
                    change({
                      asset: e.target.value,
                      references: [],
                      assetMode: "original",
                      assetConfirmed: false,
                      identityRegion: null,
                    })
                  }
                >
                  <option value="">选择已有照片</option>
                  {data.assets.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {asset && (
              <ProductRegion
                asset={asset}
                region={options.identityRegion}
                change={(area) =>
                  change({ identityRegion: area, assetConfirmed: false })
                }
              >
                <label className="agent-check-row">
                  <input
                    type="checkbox"
                    checked={!!options.assetConfirmed}
                    onChange={(e) =>
                      change({ assetConfirmed: e.target.checked })
                    }
                  />
                  <span>包装文字与标识清晰完整</span>
                </label>
              </ProductRegion>
            )}
            <button
              className="secondary"
              disabled={!!busy}
              onClick={() => setPanel("")}
            >
              完成
            </button>
            {error && <p className="error">{error}</p>}
          </div>
        </Modal>
      )}

      {(panel === "spec" || panel === "own") && (
        <Modal
          title={panel === "own" ? "使用我的文案" : "画幅与规格"}
          onClose={() => setPanel("")}
        >
          <div className="agent-fields">
            {panel === "spec" && (
              <>
                <fieldset className="spec-picker">
                  <legend>作品类型</legend>
                  {[
                    ["", "自动判断"],
                    ...Object.entries(kinds),
                  ].map(([k, l]) => (
                    <button
                      key={k || "auto"}
                      type="button"
                      aria-pressed={(options.kind || "") === k}
                      onClick={() =>
                        setOptions((o) => {
                          const { kind, ratio, ...rest } = o;
                          return k ? { ...rest, kind: k } : rest;
                        })
                      }
                    >
                      {l}
                    </button>
                  ))}
                </fieldset>
                {activeKind !== "copy" && (
                  <RatioPicker
                    value={activeRatio}
                    onChange={(ratio) => change({ ratio })}
                  />
                )}
                {activeKind === "video" ? (
                  <fieldset className="spec-picker">
                    <legend>短片时长</legend>
                    {data.videoDurations.map((n) => (
                      <button
                        key={n}
                        type="button"
                        aria-pressed={
                          (options.duration || task?.duration || 15) === n
                        }
                        onClick={() => change({ duration: n })}
                      >
                        {n} 秒
                      </button>
                    ))}
                  </fieldset>
                ) : (
                  activeKind !== "copy" && (
                    <fieldset className="spec-picker">
                      <legend>图片数量（制作前确认积分）</legend>
                      {[1, 2].map((n) => (
                        <button
                          key={n}
                          type="button"
                          aria-pressed={
                            (options.imageCount || task?.imageCount || 1) === n
                          }
                          onClick={() => change({ imageCount: n })}
                        >
                          {n} 张 · {data.prices.copy + data.prices.poster * n}{" "}
                          积分
                        </button>
                      ))}
                    </fieldset>
                  )
                )}
              </>
            )}
            <label>
              已有文案（选填，填写后跳过候选直接报价）
              <textarea
                maxLength={360}
                placeholder="第一行写标题，可换行填写正文"
                value={options.ownCopy || ""}
                onChange={(e) => change({ ownCopy: e.target.value })}
              />
            </label>
            <button
              className="primary"
              onClick={() => {
                setPanel("");
                if (task && !input)
                  setInput(options.ownCopy ? "使用我的文案" : "按这个规格制作");
                textarea.current?.focus();
              }}
            >
              <Check size={16} />
              确定规格
            </button>
          </div>
        </Modal>
      )}

      {panel === "memory" && (
        <AgentMemory
          conversationId={chat?.id}
          project={chat?.project}
          projectName={projectName}
          assets={data.assets}
          weeks={home.weeks}
          onWeeks={(weeks) => setHome((h) => ({ ...h, weeks }))}
          onChanged={() => {
            syncHome();
            if (chat?.id) api(root + "/" + chat.id).then(display).catch(() => {});
          }}
          onClose={() => setPanel("")}
        />
      )}
    </div>
  );
}
