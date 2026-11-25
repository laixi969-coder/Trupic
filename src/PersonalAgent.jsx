import React, { useEffect, useRef, useState } from "react";
import {
  ArrowUp,
  BookOpen,
  Check,
  ChevronRight,
  Clock3,
  ImagePlus,
  LoaderCircle,
  MessageSquare,
  Mic,
  Plus,
  SlidersHorizontal,
  X,
} from "lucide-react";
import { api, Modal } from "./ui.jsx";
import { RatioPicker } from "./CreationSpecs.jsx";
import ProductRegion from "./ProductRegion.jsx";
import AgentTask, { kinds } from "./AgentTask.jsx";
import AgentMemory from "./AgentMemory.jsx";
import "./agent.css";

const root = "/agent/conversations";
const activeStates = ["planning", "queued", "running", "reviewing"];
const choiceKey = () =>
  globalThis.crypto?.randomUUID?.() ||
  Date.now().toString(36) + Math.random().toString(36).slice(2);
const starters = [
  [
    "poster",
    "做一张海报",
    "/designs/industry-tea.webp",
    "想为门店做一张海报，宣传",
  ],
  ["copy", "写朋友圈文案", "/visuals/bakery.webp", "想写一条朋友圈文案，介绍"],
  ["video", "剪一条短片", "/visuals/pool.webp", "想做一条短片，介绍"],
];

export default function PersonalAgent({ data, refresh, tip, seed, clearSeed }) {
  const [home, setHome] = useState({
      conversations: [],
      projects: [],
      weeks: 1,
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
  const [workRef, setWorkRef] = useState(null),
    [project, setProject] = useState(""),
    [projectTitle, setProjectTitle] = useState(""),
    [recording, setRecording] = useState(false);
  const [assetRights, setAssetRights] = useState(false);
  const textarea = useRef(null),
    file = useRef(null),
    live = useRef(true),
    current = useRef(null),
    generation = useRef(0),
    lock = useRef(false),
    speech = useRef(null),
    end = useRef(null);
  const storage = "trupic.agent." + data.workspace;
  const speechApi = window.SpeechRecognition || window.webkitSpeechRecognition;
  const asset = data.assets.find((a) => a.id === options.asset);
  const projectName = home.projects.find((p) => p.id === chat?.project)?.title;
  const task = chat?.tasks.find((t) => t.id === target);
  const change = (v) => setOptions((o) => ({ ...o, ...v }));
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
  function reset() {
    setInput("");
    setOptions({});
    setTarget(null);
    setWorkRef(null);
    setPanel("");
    setError("");
    setAssetRights(false);
    speech.current?.abort();
  }
  async function openChat(id) {
    const version = ++generation.current;
    const c = await api(root + "/" + id + "/visit", "POST", {});
    if (live.current && version === generation.current) {
      reset();
      display(c);
    }
  }
  useEffect(() => {
    live.current = true;
    (async () => {
      const h = await syncHome();
      const stored = sessionStorage.getItem(storage);
      const id =
        h.conversations.find((c) => c.id === stored)?.id ||
        h.conversations[0]?.id;
      if (id && live.current) await openChat(id);
      if (live.current) setReady(true);
    })().catch((e) => {
      if (live.current) setError(e.message);
    });
    return () => {
      live.current = false;
      generation.current++;
      speech.current?.abort();
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
  // A focused window reloads the authoritative conversation, including changes from other devices.
  // Event cursors let a disconnected window catch up even if several worker stages elapsed.
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
        if ([...updates.values()].some((t) => !activeStates.includes(t.status)))
          await refresh();
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
      // Store the key before the request. A lost response can be retried with the same body.
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
      await refresh();
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
      if (!assetRights) throw new Error("请先确认有权使用这些素材。");
      if (files.length > 3) throw new Error("一次最多选择三张照片。");
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
    });
  }
  function voice() {
    if (recording) {
      speech.current?.stop();
      return;
    }
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
  }
  const messages = chat?.messages || [];
  const latestCard = new Map(
    messages.filter((m) => m.kind === "task").map((m) => [m.task, m.seq]),
  );
  const cards = new Map((chat?.tasks || []).map((t) => [t.id, t]));
  const showWelcome = !messages.some((m) => m.role === "user");
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
    <div className="agent-page">
      <header className="agent-bar">
        <div>
          <img src="/favicon.svg" alt="" />
          <div>
            <strong>营销助理</strong>
            {projectName && <small>{projectName}</small>}
          </div>
        </div>
        <div>
          <button
            disabled={!!busy || !ready}
            onClick={() => {
              setProject(chat?.project || "");
              setPanel("new");
            }}
          >
            <Plus size={17} />
            新对话
          </button>
          <button
            disabled={!!busy}
            onClick={() =>
              perform("history", async () => {
                await syncHome();
                setPanel("history");
              })
            }
          >
            <Clock3 size={17} />
            历史
          </button>
          <button
            aria-label="助理记忆"
            title="助理记忆"
            disabled={!!busy}
            onClick={() => setPanel("memory")}
          >
            <BookOpen size={17} />
          </button>
        </div>
      </header>
      {showWelcome && (
        <div className="agent-welcome">
          <h1>
            今天想为<span>{data.profile.name || "店里"}</span>做点什么？
          </h1>
          <div className="agent-starters">
            {starters.map(([kind, label, img, seed]) => (
              <button
                key={kind}
                disabled={!!busy}
                onClick={() => {
                  setInput(seed);
                  setOptions({ kind });
                  textarea.current?.focus();
                }}
              >
                <img src={img} alt="" />
                <b>
                  {label}
                  <ChevronRight size={15} />
                </b>
              </button>
            ))}
          </div>
        </div>
      )}
      {!showWelcome && <h1 className="agent-thread-name">{chat.title}</h1>}
      <div className="agent-messages">
        {messages.map((m) => {
          if (m.kind === "task") {
            if (latestCard.get(m.task) !== m.seq) return null;
            const t = cards.get(m.task);
            return (
              t && (
                <AgentTask
                  key={m.seq}
                  writing={writing[t.id] === t.revision}
                  writingError={
                    writingErrors[t.id]?.revision === t.revision
                      ? writingErrors[t.id].message
                      : ""
                  }
                  {...{ task: t, busy: !!busy, action, send, edit, tip }}
                />
              )
            );
          }
          if (m.kind === "topics")
            return <React.Fragment key={m.seq}>{topicCards(m)}</React.Fragment>;
          if (m.kind === "pick_work")
            return (
              <div className="agent-bubble" key={m.seq}>
                {m.text}
                <div className="agent-links">
                  {m.items.map((w) => (
                    <button
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
            );
          if (m.kind === "switch")
            return (
              <div className="agent-bubble" key={m.seq}>
                这是一个新任务。要在哪里继续？
                <div className="agent-links">
                  <button
                    disabled={!!busy}
                    onClick={() =>
                      send(m.text, { action: "branch" }, m.options)
                    }
                  >
                    另开对话
                  </button>
                  <button
                    disabled={!!busy}
                    onClick={() => send(m.text, { action: "here" }, m.options)}
                  >
                    留在这里
                  </button>
                </div>
              </div>
            );
          return (
            <div className={"agent-bubble " + m.role} key={m.seq}>
              {m.asset && (
                <img
                  className="agent-source-photo"
                  src={"/api/assets/" + m.asset + "/original"}
                  alt="本条消息的商品照片"
                />
              )}
              {m.text}
            </div>
          );
        })}
      </div>
      <form
        className="agent-composer"
        onSubmit={(e) => {
          e.preventDefault();
          send(input || (options.ownCopy ? "使用我的文案" : ""));
        }}
      >
        {(workRef ||
          task ||
          options.asset ||
          options.kind ||
          options.ownCopy) && (
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
                <img src={asset.original} alt="" />
                {asset.name}
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
          rows={3}
          placeholder={
            task
              ? "想改哪里？"
              : showWelcome
                ? "说说想推广什么，也可以附上商品照片…"
                : "继续说说你的想法…"
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
        <div className="agent-tools">
          <div>
            <button
              type="button"
              disabled={!!busy}
              onClick={() => setPanel("asset")}
            >
              <ImagePlus size={17} />
              素材
            </button>
            <button
              type="button"
              disabled={!!busy}
              onClick={() => setPanel("spec")}
            >
              <SlidersHorizontal size={17} />
              规格
            </button>
            {speechApi && (
              <button
                type="button"
                disabled={!!busy}
                aria-label={recording ? "结束录音" : "语音输入"}
                aria-pressed={recording}
                onClick={voice}
              >
                <Mic size={17} />
              </button>
            )}
          </div>
          <button
            className="agent-send"
            aria-label="发送消息"
            disabled={!!busy || !ready || !(input.trim() || options.ownCopy)}
          >
            {busy ? (
              <LoaderCircle size={19} className="spin" />
            ) : (
              <ArrowUp size={20} />
            )}
          </button>
        </div>
      </form>
      {busy && (
        <p className="agent-feedback" role="status">
          {busy === "send"
            ? "正在处理这条消息…"
            : busy === "upload"
              ? "正在上传素材…"
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
      <div className="agent-foot">
        <button
          disabled={!!busy || !ready}
          onClick={() => send("本周推荐", { action: "topics" }, {})}
        >
          查看本周选题
        </button>
        <a href="#works">我的作品</a>
        <a href="#studio">原创作台</a>
      </div>
      <div ref={end} />
      {panel === "history" && (
        <Modal title="历史对话" onClose={() => setPanel("")}>
          <div className="agent-history">
            {home.conversations.length === 0 && <p>还没有对话。</p>}
            {home.conversations.map((c) => (
              <div key={c.id}>
                <button
                  aria-current={c.id === chat?.id}
                  onClick={() => perform("open", () => openChat(c.id))}
                >
                  <MessageSquare size={17} />
                  <span>{c.title}</span>
                </button>
                <button
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
                        else {
                          reset();
                          display(null);
                        }
                      }
                    })
                  }
                >
                  <X size={15} />
                </button>
              </div>
            ))}
          </div>
        </Modal>
      )}
      {panel === "new" && (
        <Modal title="新对话" onClose={() => setPanel("")}>
          <div className="agent-fields">
            <label>
              关联项目
              <select
                value={project}
                onChange={(e) => setProject(e.target.value)}
              >
                <option value="">独立对话</option>
                {home.projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.title}
                  </option>
                ))}
                <option value="+">创建项目…</option>
              </select>
            </label>
            {project === "+" && (
              <input
                aria-label="项目名称"
                maxLength={60}
                placeholder="项目名称"
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
                  setProject(pid);
                  setProjectTitle("");
                  textarea.current?.focus();
                })
              }
            >
              开始新对话
            </button>
          </div>
        </Modal>
      )}
      {panel === "asset" && (
        <Modal title="添加素材" onClose={() => setPanel("")}>
          <div className="agent-fields">
            <label>
              <input
                type="checkbox"
                checked={assetRights}
                onChange={(e) => setAssetRights(e.target.checked)}
              />{" "}
              我有权使用所选素材
            </label>
            <input
              type="file"
              multiple
              accept="image/jpeg,image/png,image/webp"
              aria-label="选择照片"
              ref={file}
              hidden
              onChange={upload}
            />
            <button
              className="secondary"
              disabled={!!busy || !assetRights}
              onClick={() => file.current.click()}
            >
              <ImagePlus size={16} />
              上传照片（最多三张）
            </button>
            <label>
              视频节奏参考
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
                素材库
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
                  <option value="">选择照片</option>
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
                <label>
                  <input
                    type="checkbox"
                    checked={!!options.assetConfirmed}
                    onChange={(e) =>
                      change({ assetConfirmed: e.target.checked })
                    }
                  />{" "}
                  标识清晰完整
                </label>
              </ProductRegion>
            )}
            <button
              className="primary"
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
          title={panel === "own" ? "使用我的文案" : "本次创作规格"}
          onClose={() => setPanel("")}
        >
          <div className="agent-fields">
            {panel === "spec" && (
              <>
                <label>
                  作品类型
                  <select
                    value={options.kind || task?.kind || ""}
                    onChange={(e) =>
                      setOptions((o) => {
                        const { kind, ratio, ...rest } = o;
                        return e.target.value
                          ? { ...rest, kind: e.target.value }
                          : rest;
                      })
                    }
                  >
                    <option value="">根据需求判断</option>
                    {Object.entries(kinds).map(([k, l]) => (
                      <option key={k} value={k}>
                        {l}
                      </option>
                    ))}
                  </select>
                </label>
                {(options.kind || task?.kind) !== "copy" && (
                  <RatioPicker
                    value={
                      options.ratio ||
                      task?.ratio ||
                      (options.kind === "video" ? "story" : "portrait")
                    }
                    onChange={(ratio) => change({ ratio })}
                  />
                )}
                {(options.kind || task?.kind) === "video" ? (
                  <label>
                    短片时长
                    <select
                      value={options.duration || task?.duration || 15}
                      onChange={(e) =>
                        change({ duration: Number(e.target.value) })
                      }
                    >
                      {data.videoDurations.map((n) => (
                        <option value={n} key={n}>
                          {n} 秒
                        </option>
                      ))}
                    </select>
                  </label>
                ) : (
                  (options.kind || task?.kind) !== "copy" && (
                    <label>
                      图片数量
                      <select
                        value={options.imageCount || task?.imageCount || 1}
                        onChange={(e) =>
                          change({ imageCount: Number(e.target.value) })
                        }
                      >
                        {[1, 2].map((n) => (
                          <option value={n} key={n}>
                            {n} 张 · {data.prices.copy + data.prices.poster * n}{" "}
                            积分
                          </option>
                        ))}
                      </select>
                    </label>
                  )
                )}
              </>
            )}
            <label>
              已有文案
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
              用在这条消息
            </button>
          </div>
        </Modal>
      )}
      {panel === "memory" && (
        <AgentMemory
          project={chat?.project}
          projectName={projectName}
          assets={data.assets}
          weeks={home.weeks}
          onWeeks={(weeks) => setHome((h) => ({ ...h, weeks }))}
          onClose={() => setPanel("")}
        />
      )}
    </div>
  );
}
