import CopyChoices from "./CopyChoices.jsx";
import React, { useState, useEffect, useRef } from "react";
import { createRoot } from "react-dom/client";
import {
  LayoutDashboard,
  Images,
  FolderOpen,
  Compass,
  Store,
  HelpCircle,
  ShieldCheck,
  ChevronsUpDown,
  Menu,
  X,
  PanelLeft,
  Sun,
  Leaf,
  ArrowRight,
  ArrowUpRight,
  Plus,
  Sparkles,
  Paperclip,
  Lightbulb,
  SlidersHorizontal,
  Check,
  CalendarDays,
  Search,
  UploadCloud,
  Download,
  Undo2,
  Clock3,
  CheckCircle2,
  Camera,
  Trash2,
  Layers,
  History,
  Copy,
  ArrowLeft,
  Settings2,
  LogOut,
  LockKeyhole,
  RefreshCw,
  ScanLine,
  Zap,
  MessageSquare,
} from "lucide-react";
import {
  api,
  Brand,
  Modal,
  PageHead,
  Blank,
  Busy,
  CaseCard,
  Field,
  formats,
  imageUrl,
  dateText,
} from "./ui.jsx";
import Admin from "./Admin.jsx";
import { RatioPicker } from "./CreationSpecs.jsx";
import IndustryPicker from "./IndustryPicker.jsx";
import { Promotion } from "./Growth.jsx";
import { MerchantShop } from "./Commerce.jsx";
import WorkHistory from "./WorkHistory.jsx";
import AutoCreate from "./AutoCreate.jsx";
import {Support} from "./Support.jsx";
import ProductRegion from "./ProductRegion.jsx";
import {
  FontPicker,
  PosterOptions,
  ExportOptions,
  StyleGallery,
  IndustryGallery,
} from "./PosterDesign.jsx";
import "./style.css";

const navs = [
  ["home", "创作工作台", LayoutDashboard],
  ["works", "我的作品", Images],
  ["assets", "素材库", FolderOpen],
  ["inspiration", "灵感广场", Compass],
  ["promotion","邀请与推广", Store],
  ["profile", "商家档案", Store],
];
const route = () => {
  const value = decodeURIComponent(location.hash.slice(1)) || "home";
  return value === "bundles" ? "home" : value;
};
const ratios = {
  portrait: "竖版 3:4",
  square: "方形 1:1",
  story: "竖屏 9:16",
  feed: "信息流 4:5",
  landscape: "横版 16:9",
};
const initialDraft = {
  brief: "",
  kind: "poster",
  ratio: "portrait",
  resolution: 1080,
  dpi: 300,
  videoRatio: "story",
  videoResolution: 720,
  posterStyle: "auto",
  lettering: "auto",
  fontId: "profile",
  asset: "",
  assetMode: "processed",
  assetConfirmed: false,
  source: "一句话创作",
  topicId: "",
  reference: "",
};
function savedDraft() {
  try {
    return {
      ...initialDraft,
      ...JSON.parse(sessionStorage.getItem("trupic-draft") || "{}"),
    };
  } catch {
    return initialDraft;
  }
}
function OptimizedBrief({ plan, fullPosterPrompt }) {
  const brief = plan?.promptBrief;
  if (!brief) return null;
  const names = { copy: "文案指令", image: "画面指令", video: "分镜指令" };
  return (
    <details className="shot-list">
      <summary>查看优化后的创作指令</summary>
      <p className="fineprint">{brief.engine}</p>
      {plan.posterArt?.reference && <p>{plan.posterArt.reference}</p>}
      {Object.entries(brief.prompts).map(([k, v]) => (
        <div key={k}>
          <strong>{names[k]}</strong>
          <p>{v}</p>
        </div>
      ))}
      {fullPosterPrompt && <div><strong>整张海报直出提示词</strong><p style={{whiteSpace: "pre-line"}}>{fullPosterPrompt}</p></div>}
    </details>
  );
}
function promotionSource() {
  const query = new URLSearchParams(location.search);
  return { invite: query.get("invite") || "", channel: query.get("channel") || "" };
}
function clearPromotionSource() {
  const url = new URL(location.href);
  url.searchParams.delete("invite");
  url.searchParams.delete("channel");
  history.replaceState(history.state, "", url);
}
function App() {
  const [data, setData] = useState(null),
    [page, setPage] = useState(route),
    [modal, setModal] = useState(null),
    [mobile, setMobile] = useState(false),
    [toast, setToast] = useState(""),
    [busy, setBusy] = useState(""),
    [error, setError] = useState(""),
    [bootError, setBootError] = useState("");
  const [draft, setDraft] = useState(savedDraft),
    [showParams, setParams] = useState(false),
    [chosenCopy, setChosenCopy] = useState(null),
    [preview, setPreview] = useState(null),
    [work, setWork] = useState(null),
    [version, setVersion] = useState(null),
    [pickRegion,setPickRegion] = useState(false),
    [detailTab, setDetailTab] = useState("copy"),
    [caseItem, setCase] = useState(null),
    [assetItem, setAssetItem] = useState(null),
    [filter, setFilter] = useState("全部"),
    [search, setSearch] = useState(""),
    [job, setJob] = useState(null);
  const [revisionQuote, setRevisionQuote] = useState(null);
  const [editBox,setEditBox] = useState(null);
  const [editText,setEditText] = useState("");
  const [editField,setEditField] = useState("");
  const [duplicate,setDuplicate] = useState(false);
  const [shortChoice, setShortChoice] = useState(0);
  const [profile, setProfile] = useState({}),
    [auth, setAuth] = useState({ login: "", password: "" }),
    [accountMode, setAccountMode] = useState("register");
  const fileRef = useRef(),
    uploadPurpose = useRef("library"),
    textarea = useRef(),
    timer = useRef(),
    token = useRef("");
  const loading = useRef(false);
  const tip = (s) => {
    clearTimeout(timer.current);
    setToast(s);
    timer.current = setTimeout(() => setToast(""), 3300);
  };
  const refresh = async () => {
    const d = await api("/state");
    if (!Array.isArray(d?.videoDurations) || d.prices?.version == null) {
      throw new Error("工作台与服务端版本不一致，请重启新版服务后重新连接。");
    }
    setData(d);
    return d;
  };
  const go = (p) => {
    setMobile(false);
    setModal(null);
    if (route() !== p) location.hash = p;
  };
  function open(m) {
    setError("");
    setModal(m);
    setMobile(false);
  }
  function close() {
    setModal(null);
    setError("");
  }
  useEffect(() => {
    refresh()
      .then((d) => {
        setProfile(d.profile);
        const { invite, channel } = promotionSource();
        if (invite && !d.login) setModal("account");
        if (invite && d.login) api("/promotion/claim","POST",{code:invite, channel}).then(clearPromotionSource).catch(e=>tip(e.message));
        setBootError("");
        const j = d.jobs.find((j) => !j.autoCreation && ["queued", "running"].includes(j.state));
        if (j) {
          setJob(j);
        }
      })
      .catch((e) => setBootError(e.message));
    const fn = () => {
      const p = route();
      setPage(p);
      setSearch("");
      setFilter("全部");
      setMobile(false);
      setModal(null);
      setError("");
      window.scrollTo(0, 0);
    };
    addEventListener("hashchange", fn);
    return () => {
      removeEventListener("hashchange", fn);
    };
  }, []);
  useEffect(() => {
    try {
      sessionStorage.setItem("trupic-draft", JSON.stringify(draft));
    } catch {}
  }, [draft]);
  useEffect(() => {
    if (!page.startsWith("work/")) return;
    let active = true;
    setWork(null);
    setError("");
    api("/works/" + page.split("/")[1])
      .then((w) => {
        if (active) {
          setWork(w);
          setVersion(w.current);
          setDetailTab("copy");setPickRegion(false);setEditBox(null);setEditText("");setEditField("");setDuplicate(false);
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [page]);
  useEffect(() => {
    if (!job?.id) return;
    let active = true,
      h;
    const poll = async () => {
      try {
        const j = await api("/jobs/" + job.id);
        if (!active) return;
        if (j.state === "complete") {
          setJob(null);
          setModal(null);
          await refresh();
          const dest = "work/" + j.work;
          if (route() === dest) {
            const w = await api("/works/" + j.work);
            setWork(w);
            setVersion(j.version);
          } else go(dest);
          tip("作品已保存到「我的作品」");
        } else if (j.state === "failed") {
          setJob(null);
          setError(j.error || "制作中断，请重试。");
          setModal("jobError");
          await refresh();
        } else {
          h = setTimeout(poll, 850);
        }
      } catch (e) {
        if (active) {
          setError(e.message);
          h = setTimeout(poll, 2300);
        }
      }
    };
    poll();
    return () => {
      active = false;
      clearTimeout(h);
    };
  }, [job?.id]);
  async function run(label, fn) {
    if (loading.current) return;
    loading.current = true;
    setBusy(label);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(e.message || "操作失败，请重试。");
    } finally {
      loading.current = false;
      setBusy("");
    }
  }
  function patch(d) {
    setDraft((p) => ({
      ...p,
      ...("asset" in d && d.asset !== p.asset ? { visualDetail: null } : {}),
      ...d,
    }));
    setError("");
  }
  function chooseBrief(
    brief,
    reference = "",
    source = "灵感广场",
    topicId = "",
  ) {
    go("home");
    patch({ brief, reference, source, topicId, extraFacts: "" });
    setTimeout(() => {
      textarea.current?.focus();
      textarea.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 70);
  }
  function pickFile(purpose) {
    uploadPurpose.current = purpose;
    fileRef.current?.click();
  }
  const selected = data?.assets.find((a) => a.id === draft.asset);
  const editingVideo = draft.kind === "video" || /短片|视频|动态海报/.test(draft.brief);
  function useAsset(a) {
    const check = a.risk || a.action === "主体抠图";
    setAssetItem(a);
    patch({
      asset: a.id,
      identityRegion: null,
      assetMode: "processed",
      assetConfirmed: !check,
    });
    if (check) open("checkAsset");
    else {
      close();
      tip("素材已添加 · " + a.action);
    }
  }
  async function upload(e) {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    await run("upload", async () => {
      if (f.size > 12 * 1024 * 1024)
        throw new Error("请选择小于 12 MB 的图片。");
      const fd = new FormData();
      fd.append("image", f);
      const a = await api("/assets", "POST", fd);
      await refresh();
      setAssetItem(a);
      if (uploadPurpose.current === "compose") {
        useAsset(a);
      } else {
        setModal("asset");
      }
    });
  }
  function plan() {
    if (!draft.brief.trim()) {
      textarea.current?.focus();
      setError("先写一句想宣传的商品或经营需求。");
      return;
    }
    if (selected && !draft.assetConfirmed && draft.kind !== "copy") {
      setAssetItem(selected);
      open("checkAsset");
      return;
    }
    run("plan", async () => {
      const p = await api("/preview", "POST", {
        ...draft,
        ...(draft.kind === "video"
          ? { ratio: draft.videoRatio, resolution: draft.videoResolution }
          : {}),
      }).catch((e) => {
        if (selected && /标出要保真|所选标识|原图标识区域/.test(e.message)) {
          setAssetItem(selected);
          open("checkAsset");
        }
        throw e;
      });
      setPreview(p);
      token.current = crypto.randomUUID();
      open("preview");
    });
  }
  async function quoteRevision(action, ratio) {
    await run("quote", async () => {
      const q = await api("/works/" + work.id + "/revision-quote", "POST", {base:version,action,ratio,...(action==="region"?{instruction:editText,region:editBox,duplicate}:action==="edit"?{instruction:editText,field:editField,duplicate}:{})});
      token.current = crypto.randomUUID();
      setRevisionQuote(q); setShortChoice(0); open("revisionQuote");
    });
  }
  async function launch(kind = "new") {
    await run("generate", async () => {
      const req =
        kind === "new"
          ? {
              ...draft,
              confirmed: true,
              confirmedCost: preview.cost,
              quote: preview.quote,
              copyChoice: chosenCopy?.quote === preview.quote ? chosenCopy.token : "",
              requestKey: token.current,
            }
          : { quote:revisionQuote.quote, option:shortChoice, confirmed:true, confirmedCost:revisionQuote.cost, requestKey:token.current };
      const j = await api(
        kind === "new" ? "/jobs" : "/works/" + work.id + "/revise",
        "POST",
        req,
      );
      setJob(j);
      open("progress");
    });
  }
  function showAccount() {
    setAccountMode(data?.login ? "info" : "register");
    setAuth({ login: "", password: "" });
    open("account");
  }
  const section = page.startsWith("work/") ? "works" : page;
  const pageName =
    navs.find((n) => n[0] === section)?.[1] ||
    (section === "admin" ? "运营管理" : "创作工作台");
  function navItem([id, label, Icon]) {
    return (
      <button
        key={id}
        className={"navitem " + (section === id ? "active" : "")}
        aria-current={section === id ? "page" : undefined}
        onClick={() => {
          go(id);
          if (id === "profile") setProfile(data?.profile || {});
        }}
      >
        <Icon size={18} />
        <span>{label}</span>
        {id === "works" && data?.works.length > 0 && (
          <small>{data.works.length}</small>
        )}
      </button>
    );
  }
  function navAdmin() {
    if (data.admin) {
      go("admin");
    } else {
      setAuth({ password: "" });
      open("adminLogin");
    }
  }
  if (!data)
    return (
      <div className="boot">
        <Brand />
        {bootError ? (
          <>
            <p>{bootError}</p>
            <button className="primary" onClick={() => location.reload()}>
              重新连接
            </button>
          </>
        ) : (
          <Busy text="正在打开工作台…" />
        )}
      </div>
    );
  const versionData = work?.versions.find((v) => v.n === version);
  const densePosterAdvice = work?.kind === "poster" && version === 1 && versionData?.brief.includes("满屏字");
  const currentCases = data.cases.filter(
    (c) =>
      (filter === "全部" || c.industry === filter) &&
      (c.title + c.industry + c.method).includes(search),
  );
  const currentWorks = data.works.filter(
    (w) => (filter === "全部" || w.kind === filter) && w.title.includes(search),
  );
  const onCase = (c) => {
    setCase(c);
    open("case");
  };
  const toastError =
    error &&
    !modal &&
    !["home", "profile"].includes(page) &&
    !page.startsWith("work/");
  return (
    <div className="shell">
      {mobile && (
        <button
          className="backdrop"
          aria-label="关闭导航"
          onClick={() => setMobile(false)}
        />
      )}
      <aside className={"sidebar " + (mobile ? "mobileopen" : "")}>
        <button
          className="brandbtn"
          onClick={() => go("home")}
          aria-label="响指出片首页"
        >
          <Brand />
        </button>
        <div className="nav-label">工作空间</div>
        <nav>{navs.slice(0, 3).map(navItem)}</nav>
        <div className="nav-label second">品牌与灵感</div>
        <nav>{navs.slice(3).map(navItem)}</nav>
        <div className="sidebottom">

          <button className={"navitem subdued" + (section === "admin" ? " active" : "")} aria-current={section === "admin" ? "page" : undefined} onClick={navAdmin}>
            <Settings2 size={17} />
            运营管理
          </button>
          <button className="accountbtn" onClick={showAccount}>
            <span className="avatar">
              <Store size={18} />
            </span>
            <span>
              <strong>{data.profile.name || "我的工作室"}</strong>
              <small>{data.login || "商家工作空间"}</small>
            </span>
            <ChevronsUpDown size={15} />
          </button>
        </div>
      </aside>
      <main className="main">
        <div className="topbar">
          <div className="crumb">
            <button
              className="mobile-toggle iconbtn"
              aria-label="打开导航"
              onClick={() => setMobile(true)}
            >
              <Menu size={21} />
            </button>
            <PanelLeft size={16} className="desktopicon" />
            <span className="crumb-parent">商家工作空间</span>
            <span className="slash">/</span>
            <b>{page.startsWith("work/") ? "作品详情" : pageName}</b>
          </div>
          <div className="topactions">
            <button className="credit" onClick={() => open("credits")}>
              <Zap size={14} fill="currentColor" />
              <b>{data.credits}</b> 积分
            </button>
            <span className="vertical-line" />
            <button
              aria-label="我的账号"
              className="topavatar"
              onClick={showAccount}
            >
              {(data.profile.name || "商").slice(0, 1)}
            </button>
          </div>
        </div>
        <div className="content" key={section}>
          {(page === "home" || page === "bundles") && (
            <>
              <div className="homehead">
                <h1>创作工作台</h1>
                <div className="today">
                  <CalendarDays size={15} />
                  {new Intl.DateTimeFormat("zh-CN", {
                    month: "long",
                    day: "numeric",
                    weekday: "long",
                  }).format(new Date())}
                </div>
              </div>
              <div className="hero">
                <img
                  src="/visuals/studio-hero.webp"
                  alt="抹茶与柑橘饮品的创意海报拼贴"
                />
                <div className="herocopy">
                  <div className="studio-label">
                    <span className="pinwheel">✳</span> TRUPIC CREATIVE STUDIO
                  </div>
                  <h2>
                    把一句想法，
                    <br />
                    <em>变成营销作品。</em>
                  </h2>
                  <p>为你的生意，创作文案、海报与短片。</p>
                </div>
              </div>
              <AutoCreate durations={data.videoDurations} prices={data.prices} profile={data.profile} assets={data.assets} draft={draft} patch={patch} refresh={refresh} textRef={textarea}
                checkAsset={(asset) => { setAssetItem(asset); open("checkAsset"); }}
                options={<details open={showParams} onToggle={(e) => setParams(e.currentTarget.open)}>
                  <summary>版式与字体</summary>
                  <PosterOptions draft={draft} patch={patch} data={data} refresh={refresh} />
                </details>} />
              <div className="recline">
                <span>
                  <Lightbulb size={15} />
                  本周灵感
                </span>
                {data.recs.slice(0, 2).map((r) => (
                  <button
                    key={r.id}
                    onClick={() => chooseBrief(r.brief, "", r.id, r.topicId)}
                  >
                    {r.title}
                    {r.adopted && " · 已制作"}
                    <ArrowUpRight size={12} />
                  </button>
                ))}
              </div>
              <section className="gallery-home">
                <div className="sectionhead">
                  <div className="sectitle">
                    <span className="section-mark" />
                    <h2>精选创意</h2>
                  </div>
                  <button className="textbtn" onClick={() => go("inspiration")}>
                    浏览灵感广场
                    <ArrowRight size={15} />
                  </button>
                </div>
                <div className="casegrid">
                  {data.cases.map((c) => (
                    <CaseCard key={c.id} item={c} onClick={onCase} />
                  ))}
                </div>
              </section>
              {data.works.length > 0 && (
                <section>
                  <div className="sectionhead">
                    <h2>最近作品</h2>
                    <button className="textbtn" onClick={() => go("works")}>
                      查看全部
                      <ArrowRight size={14} />
                    </button>
                  </div>
                  <div className="workgrid">
                    {data.works.slice(0, 4).map((w) => (
                      <WorkCard
                        key={w.id}
                        work={w}
                        onClick={() => go("work/" + w.id)}
                      />
                    ))}
                  </div>
                </section>
              )}
            </>
          )}
          {page === "inspiration" && (
            <>
              <PageHead
                title="灵感广场"
                desc="看看不同生意的创意方法，选一个角度开始。"
              />
              <div className="sectionhead">
                <h2>本周营销主题</h2>
                <small className="muted">选题免费</small>
              </div>
              <div className="recgrid">
                {data.recs.map((r, i) => (
                  <button
                    key={r.id}
                    className={"reccard r" + i}
                    onClick={() => chooseBrief(r.brief, "", r.id, r.topicId)}
                  >
                    <span>
                      {i === 0 ? (
                        <Sun size={17} />
                      ) : i === 1 ? (
                        <CalendarDays size={17} />
                      ) : (
                        <Leaf size={17} />
                      )}{" "}
                      {r.tag}
                      {r.adopted && " · 已制作"}
                    </span>
                    <h3>{r.title}</h3>
                    <p>{r.brief}</p>
                    <b>
                      用这个主题 <ArrowUpRight size={14} />
                    </b>
                  </button>
                ))}
              </div>
              <div className="sectionhead">
                <h2>行业海报样张</h2>
                <small className="muted">原创概念示意</small>
              </div>
              <IndustryGallery
                examples={data.posterExamples}
                onChoose={(s) => {
                  chooseBrief(s.brief, "", "行业海报 · " + s.name);
                  patch({ kind: "poster", posterStyle: s.style });
                }}
              />
              <div className="sectionhead">
                <h2>海报版式</h2>
              </div>
              <StyleGallery
                styles={data.posterStyles}
                onChoose={(s) => {
                  go("home");
                  patch({ kind: "poster", posterStyle: s.id });
                  setParams(true);
                  setTimeout(() => textarea.current?.focus(), 60);
                }}
              />
              <div className="sectionhead">
                <h2>创意案例</h2>
              </div>
              <Toolbar
                filters={["全部", "茶饮咖啡", "休闲娱乐", "烘焙甜品"]}
                {...{ filter, setFilter, search, setSearch }}
              />
              <div className="casegrid">
                {currentCases.map((c) => (
                  <CaseCard key={c.id} item={c} onClick={onCase} />
                ))}
              </div>
              {!currentCases.length && (
                <Blank title="没有匹配的案例" desc="试试其他关键词或行业。" />
              )}
            </>
          )}
          {page === "works" && (
            <>
              <PageHead
                title="我的作品"
                desc="查看成品、下载文件，或继续打磨一个创意。"
              >
                <button className="primary" onClick={() => go("home")}>
                  <Plus size={16} />
                  新建创作
                </button>
              </PageHead>
              <Toolbar
                filters={["全部", "poster", "copy", "video"]}
                {...{ filter, setFilter, search, setSearch }}
              />
              {data.jobs.map((j) => (
                <div className="jobrow" key={j.id}>
                  <Clock3 size={17} />
                  {j.state === "failed"
                    ? "创作中断 · " + j.error
                    : "作品正在制作中"}
                  <button
                    className="textbtn"
                    onClick={() =>
                      j.state === "failed"
                        ? run("retry", async () => {
                            await api("/jobs/" + j.id + "/retry", "POST", {});
                            setJob(j);
                            open("progress");
                          })
                        : (setJob(j), open("progress"))
                    }
                  >
                    {j.state === "failed" ? "重新制作" : "查看进度"}
                  </button>
                </div>
              ))}
              <WorkHistory works={currentWorks} total={data.works.length} refresh={refresh}
                renderCard={w => <WorkCard work={w} onClick={() => go("work/" + w.id)} />} />
              {!currentWorks.length && (
                <Blank
                  icon={Layers}
                  title={
                    data.works.length
                      ? "没有匹配的作品"
                      : "你的第一份作品，从一句话开始"
                  }
                  desc={
                    data.works.length
                      ? "试试其他类型或关键词。"
                      : "完成创作后，你的海报、文案和短片会保存在这里。"
                  }
                  action={data.works.length ? undefined : "开始创作"}
                  onClick={() => go("home")}
                />
              )}
            </>
          )}
          {page === "promotion" && (
            <>
              <PageHead title="邀请与推广" />
              <Promotion key={data.login || "guest"} onLogin={showAccount} />
            </>
          )}
          {page === "assets" && (
            <>
              <PageHead
                title="素材库"
                desc="保存真实商品照片，上传时自动检查清晰度、曝光和背景。"
              >
                <button
                  className="primary"
                  disabled={!!busy}
                  onClick={() => pickFile("library")}
                >
                  <UploadCloud size={16} />
                  {busy === "upload" ? "正在检测" : "上传素材"}
                </button>
              </PageHead>
              {data.assets.length ? (
                <div className="assetgrid">
                  {data.assets.map((a) => (
                    <button
                      className="assetcard"
                      key={a.id}
                      onClick={() => {
                        setAssetItem(a);
                        open("asset");
                      }}
                    >
                      <img src={a.url} alt={a.name} />
                      <h3>{a.name}</h3>
                      <p>
                        {a.width} × {a.height}
                        <span className={a.risk ? "warnpill" : "pill"}>
                          {a.action}
                        </span>
                      </p>
                    </button>
                  ))}
                </div>
              ) : (
                <Blank
                  icon={Camera}
                  title="为你的商品留一张好照片"
                  desc="支持 JPG、PNG 和 WebP，单张最大 12 MB。"
                  action="上传第一张素材"
                  onClick={() => pickFile("library")}
                />
              )}
            </>
          )}
          {page === "profile" && (
            <>
              <PageHead
                title="商家档案"
                desc="保存已确认的经营信息，下次创作会自动参考。"
              />
              <form
                className="formpanel"
                onSubmit={(e) => {
                  e.preventDefault();
                  run("save", async () => {
                    await api("/profile", "POST", profile);
                    await refresh();
                    tip("商家档案已保存");
                  });
                }}
              >
                <div className="formtitle">
                  <Store size={20} />
                  <h2>经营信息</h2>
                </div>
                <div className="fieldgrid">
                  <Field
                    name="name"
                    label="商家名称（选填）"
                    form={profile}
                    set={setProfile}
                    placeholder="例如：山野茶事"
                  />
                  <Field
                    name="product"
                    label="主要商品或服务"
                    form={profile}
                    set={setProfile}
                    placeholder="例如：抹茶拿铁"
                  />
                  <IndustryPicker profile={profile} setProfile={setProfile}/>
                  <Field
                    name="city"
                    label="所在地区"
                    form={profile}
                    set={setProfile}
                    placeholder="例如：杭州"
                  />
                  <Field
                    name="audience"
                    label="目标顾客"
                    form={profile}
                    set={setProfile}
                    placeholder="例如：附近上班族"
                  />
                  <Field
                    name="tone"
                    label="表达偏好"
                    form={profile}
                    set={setProfile}
                    options={["自然亲切", "简洁直接", "轻松有趣", "沉静克制"]}
                  />
                  <FontPicker
                    profile
                    fonts={data.fonts}
                    value={profile.brandFont || ""}
                    onChange={(brandFont) =>
                      setProfile((old) => ({ ...old, brandFont }))
                    }
                    onRefresh={refresh}
                  />
                </div>
                <Field
                  name="facts"
                  label="已确认的卖点与经营事实"
                  form={profile}
                  set={setProfile}
                  area
                  limit={400}
                  placeholder="填写可以公开使用的信息，例如营业时间、真实原料或已确定的优惠。"
                />
                <div className="formend">
                  {error && <span className="error">{error}</span>}
                  <button className="primary" disabled={!!busy}>
                    <Check size={16} />
                    保存档案
                  </button>
                </div>
              </form>
              <div className="memorypanel">
                <History size={19} />
                <div>
                  <h3>创作记忆</h3>
                  <p>
                    {data.works.length
                      ? "最近的标题及创意方向会作为下一次创作的参考。"
                      : "完成第一份作品后，这里会保留使用过的标题和创意方向。"}
                  </p>
                  <div className="memorytags">
                    {data.works.slice(0, 6).map((w) => (
                      <button key={w.id} onClick={() => go("work/" + w.id)}>
                        {w.title}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            </>
          )}
          {page.startsWith("work/") &&
            (!work ? (
              <div className="empty">
                {error || <Busy text="正在打开作品" />}
              </div>
            ) : (
              <>
                <button className="textbtn back" onClick={() => go("works")}>
                  <ArrowLeft size={15} />
                  我的作品
                </button>
                <PageHead
                  title={versionData.title}
                  desc={
                    formats[work.kind].name +
                    " · " +
                    dateText(work.created) +
                    " · 版本 " +
                    version +
                    (work.kind !== "copy" && versionData.plan.output
                      ? " · " +
                        versionData.plan.output.width +
                        " × " +
                        versionData.plan.output.height +
                        (work.kind === "poster"
                          ? " · " + versionData.plan.output.dpi + " DPI"
                          : " · 24 fps")
                      : "")
                  }
                >
                  <div className="result-downloads">
                    {versionData.openDesignSource && (
                      <a className="secondary" href={versionData.openDesignSource} download>
                        下载 Open Design 剪辑工程
                      </a>
                    )}
                    {versionData.editSource && <a className="secondary" href={versionData.editSource} download>下载剪辑素材包</a>}
                    {versionData.designSource && <a className="secondary" href={versionData.designSource} download>下载分层 SVG</a>}
                    <a className="primary" href={versionData.download} download>
                      <Download size={16} />
                      下载{formats[work.kind].name}
                    </a>
                  </div>
                </PageHead>
                <div className="resultgrid">
                  <div className="resultvisual">
                    {work.kind === "video" ? (
                      <video
                        key={versionData.video}
                        controls muted
                        playsInline
                        src={versionData.video}
                        poster={versionData.poster}
                      />
                    ) : work.kind === "copy" ? (
                      <article className="copy-sheet">
                        <span>TRUPIC / COPY</span>
                        <h2>{versionData.title}</h2>
                        <p>{versionData.body}</p>
                        <b>{versionData.cta}</b>
                      </article>
                    ) : (
                      <div className="interactive-poster"><img src={versionData.poster} alt={versionData.title} />
                        {pickRegion && versionData.editRegions?.map((r,i)=><button key={i} className="copy-region"
                          style={{left:(r.box[0]*100)+"%",top:(r.box[1]*100)+"%",width:((r.box[2]-r.box[0])*100)+"%",height:((r.box[3]-r.box[1])*100)+"%"}}
                          aria-label={"修改"+({title:"标题",body:"正文",cta:"行动句"})[r.field]} onClick={()=>{
                            setEditField(r.field);setEditText(versionData[r.field]);setPickRegion(false);
                            document.getElementById("revision-text")?.focus();
                          }}/>)}</div>
                    )}
                  </div>
                  <div className="resultside">
                    <div className="resultpanel">
                      <div className="detailtabs">
                        {[
                          ["copy", "成品文案"],
                          ["quality", "检查记录"],
                          ["versions", "版本历史"],
                        ].map(([id, l]) => (
                          <button
                            className={detailTab === id ? "sel" : ""}
                            key={id}
                            onClick={() => setDetailTab(id)}
                          >
                            {l}
                          </button>
                        ))}
                      </div>
                      {detailTab === "copy" ? (
                        <>
                          <h3>{versionData.title}</h3>
                          <p className="pre">{versionData.body}</p>
                          <p>{versionData.cta}</p>
                          {versionData.storyboard && (
                            <details className="shot-list">
                              <summary>查看短片分镜</summary>
                              <ol>
                                {versionData.storyboard.map((s) => (
                                  <li key={s.start}>
                                    <small>
                                      {s.start}–{s.end} 秒 · {s.camera}
                                    </small>
                                    <strong>{s.line}</strong>
                                    {s.caption && <span>{s.caption}</span>}
                                    {s.evidence && <span>{s.purpose}</span>}
                                  </li>
                                ))}
                              </ol>
                            </details>
                          )}
                          <button
                            className="toolbtn"
                            onClick={() =>
                              run("copy", async () => {
                                await navigator.clipboard.writeText(
                                  [
                                    versionData.title,
                                    versionData.body,
                                    versionData.cta,
                                  ].join("\n\n"),
                                );
                                tip("文案已复制");
                              })
                            }
                          >
                            <Copy size={14} />
                            复制文案
                          </button>
                        </>
                      ) : detailTab === "quality" ? (
                        <>
                          <OptimizedBrief plan={versionData.plan} fullPosterPrompt={versionData.fullPosterPrompt} />
                          <div className="checklist">
                            {versionData.quality.map((q) => (
                              <div key={q.label}>
                                <CheckCircle2 size={16} />
                                <span>
                                  <b>{q.label}</b>
                                  <small>{q.detail}</small>
                                </span>
                              </div>
                            ))}
                          </div>
                          <p className="fineprint">
                            {versionData.engine} ·{" "}
                            {versionData.visualEngine || "本地排版"} ·{" "}
                            {versionData.plan.rule} ·{" "}
                            {versionData.plan.reference}
                          </p>
                        </>
                      ) : (
                        <div className="versions">
                          {work.versions.map((v) => (
                            <button
                              key={v.n}
                              className={v.n === version ? "sel" : ""}
                              onClick={() => setVersion(v.n)}
                            >
                              <span>
                                版本 {v.n}{" "}
                                {v.n === work.current ? "· 当前" : ""}
                              </span>
                              <small>{v.title}</small>
                            </button>
                          ))}
                          {version !== work.current && (
                            <button
                              className="toolbtn"
                              onClick={() =>
                                run("restore", async () => {
                                  await api(
                                    "/works/" + work.id + "/restore/" + version,
                                    "POST",
                                    {},
                                  );
                                  setWork(await api("/works/" + work.id));
                                  await refresh();
                                  tip("已设为当前版本");
                                })
                              }
                            >
                              <Undo2 size={14} />
                              使用此版本
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                    <Support key={work.id} work={work.id}/>
                    <section className="formpanel"><h3>修改作品</h3>
                      {!!versionData.editRegions?.length && <button className="secondary" onClick={()=>{setPickRegion(!pickRegion);document.querySelector(".interactive-poster")?.scrollIntoView({block:"center"});}}>{pickRegion?"退出选区":"点选海报文字修改"}</button>}
                      <label className="field">修改位置<select value={editField} onChange={e=>setEditField(e.target.value)}>
                        <option value="">按一句话要求修改</option><option value="title">标题</option><option value="body">正文</option><option value="cta">行动句</option>{work.kind==="poster" && <option value="background">背景选区</option>}
                      </select></label>
                      {editField==="background" && <ProductRegion background asset={{original:versionData.poster}} region={editBox} change={setEditBox}/>}
                      <label className="field">{editField==="background"?"选区修改要求":editField?"替换文字":"修改要求"}<textarea id="revision-text" maxLength={400} value={editText} onChange={e=>setEditText(e.target.value)} placeholder={editField==="background"?"提亮、压暗，或描述要重绘的背景":editField?"写下新的文字":"例如：48元改成38元；换一张"}/></label>
                      <label className="checkline"><input type="checkbox" checked={duplicate} onChange={e=>setDuplicate(e.target.checked)}/> 照这个再做，另存作品</label>
                      <button className="secondary" disabled={!editText.trim()||!!busy||(editField==="background"&&!editBox)} onClick={()=>quoteRevision(editField==="background"?"region":"edit")}>查看修改与积分</button>
                    </section>
                    <div className="advice">
                      <span>
                        <Sparkles size={16} />
                        专业建议
                      </span>
                      <h3>
                        {densePosterAdvice
                          ? "给标题多留一点空间"
                          : "试试另一种开场方式"}
                      </h3>
                      <p>
                        {densePosterAdvice
                          ? "把主标题和正文分开排，保留原文和原版供对照。"
                          : `建议换成「${versionData.suggestion?.title}」，保留原始版本供对照。`}
                      </p>
                      <button
                        className="secondary"
                        disabled={!!busy || !!job}
                        onClick={() => quoteRevision(densePosterAdvice ? "layout" : "revision")}
                      >
                        <Check size={14} />
                        一键应用建议
                      </button>
                      {versionData.layoutSuggestion && (
                        <>
                          <p>{versionData.layoutSuggestion.layoutIntent || versionData.layoutSuggestion.intent}</p>
                          <button
                            className="textbtn layout-suggestion"
                            disabled={!!busy || !!job}
                            onClick={() => quoteRevision("layout")}
                          >
                            {versionData.layoutSuggestion.buttonLabel || `应用${versionData.layoutSuggestion.name}版式`}
                          </button>
                        </>
                      )}
                      <div className="advice-actions">
                        <button
                          className="textbtn"
                          disabled={!!busy || !!job}
                          onClick={() => quoteRevision("redesign")}
                        >
                          <RefreshCw size={14} />
                          换个创意
                        </button>
                        <button className="textbtn" disabled={!!busy || !!job} onClick={()=>quoteRevision("shorten")}>文案短一点</button>
                        {work.kind !== "copy" && (
                          <button className="textbtn" disabled={!!busy || !!job} onClick={()=>quoteRevision("image")}>换一张，保留文案</button>
                        )}
                      </div>
                      {work.kind !== "copy" && (
                        <details><summary>照这个再做 · 换画幅</summary><RatioPicker value={versionData.ratio} onChange={r=>r !== versionData.ratio && quoteRevision("ratio",r)} /></details>
                      )}
                    </div>
                    <details className="original">
                      <summary>原始需求与创意依据</summary>
                      <p>{versionData.brief}</p>
                      {versionData.plan.topic && (
                        <p>
                          本周主题 · {versionData.plan.topic.title} ·{" "}
                          {versionData.plan.topic.basis}
                          {versionData.plan.topic.relevance && " " + versionData.plan.topic.relevance}
                          {versionData.plan.topic.recentUses != null && " 近期相同主题已用 " + versionData.plan.topic.recentUses + " 次。"}
                          {versionData.plan.topic.source && <a href={versionData.plan.topic.source} target="_blank" rel="noreferrer">查看事件来源</a>}
                        </p>
                      )}
                      <p>推测受众 · {versionData.plan.audience}</p>
                      <p>创意方向 · {versionData.plan.angle}</p>
                    </details>
                  </div>
                </div>
                {error && !modal && <div className="error">{error}</div>}
              </>
            ))}
          {page === "admin" &&
            (data.admin ? (
              <Admin tip={tip} />
            ) : (
              <Blank
                icon={ShieldCheck}
                title="运营管理"
                desc="使用管理密码查看审核和策略版本。"
                action="管理员登录"
                onClick={navAdmin}
              />
            ))}
          {!navs.some((n) => n[0] === page) &&
            !page.startsWith("work/") &&
            page !== "admin" && (
              <Blank
                title="页面不存在"
                desc="返回工作台继续创作。"
                action="返回工作台"
                onClick={() => go("home")}
              />
            )}
          {toastError && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
        </div>
      </main>
      <input
        type="file"
        accept="image/jpeg,image/png,image/webp"
        ref={fileRef}
        onChange={upload}
        hidden
      />
      {modal === "case" && caseItem && (
        <Modal title="创意案例" wide onClose={close}>
          <div className="case-detail">
            <img src={imageUrl(caseItem.id)} alt={caseItem.title} />
            <div>
              <span className="pill">{caseItem.industry}</span>
              <h2>{caseItem.title}</h2>
              <h4>可借鉴的方法</h4>
              <h3>{caseItem.method}</h3>
              <p>{caseItem.lesson}</p>
              <small className="muted">Trupic 原创概念案例 · AI 生成视觉</small>
              <button
                className="primary"
                onClick={() => chooseBrief(caseItem.brief, caseItem.id)}
              >
                <Sparkles size={16} />
                借用这个创意
              </button>
            </div>
          </div>
        </Modal>
      )}
      {modal === "chooseAsset" && (
        <Modal title="添加创作素材" onClose={close}>
          <button
            className="uploadbox"
            disabled={!!busy}
            onClick={() => pickFile("compose")}
          >
            <UploadCloud size={27} />
            <b>{busy === "upload" ? "正在检查图片…" : "上传商品或门店照片"}</b>
            <small>JPG、PNG、WebP · 最大 12 MB</small>
          </button>
          {data.assets.length > 0 && (
            <>
              <h4>从素材库选择</h4>
              <div className="pickergrid">
                {data.assets.map((a) => (
                  <button
                    key={a.id}
                    onClick={() => {
                      useAsset(a);
                    }}
                  >
                    <img src={a.url} alt="" />
                    <span>{a.name}</span>
                  </button>
                ))}
              </div>
            </>
          )}
          {error && <p className="error">{error}</p>}
        </Modal>
      )}
      {(modal === "asset" || modal === "checkAsset") && assetItem && (
        <Modal
          title={modal === "asset" ? "素材详情" : "核对商品素材"}
          onClose={close}
        >
          <div className="asset-preview">
            <img
              src={
                draft.assetMode === "original" && modal === "checkAsset"
                  ? assetItem.original
                  : assetItem.url
              }
              alt={assetItem.name}
            />
          </div>
          <h3 className="assetname">{assetItem.name}</h3>
          <div className="infochip">
            <ScanLine size={15} />
            {assetItem.width} × {assetItem.height}
            <span>·</span>
            {assetItem.action}
          </div>
          <p>{assetItem.detail}</p>
          {modal === "checkAsset" && !assetItem.risk && (
            <ProductRegion
              key={assetItem.id}
              asset={assetItem}
              region={draft.identityRegion}
              change={(identityRegion) =>
                patch({ identityRegion, assetConfirmed: false })
              }
            />
          )}
          {modal === "checkAsset" && !assetItem.risk && editingVideo && (
            <ProductRegion
              key={assetItem.id + "-detail"}
              detail
              asset={assetItem}
              region={draft.visualDetail?.region}
              change={(region) => patch({
                visualDetail: region ? { region, label: draft.visualDetail?.label || "" } : null,
                assetConfirmed: false,
              })}
            >
              <label>框内看得见的卖点
                <input maxLength={20} placeholder="例如：杯壁上清晰的刻度"
                  value={draft.visualDetail?.label || ""}
                  onChange={(e) => patch({
                    visualDetail: { ...draft.visualDetail, label: e.target.value }, assetConfirmed: false,
                  })} />
              </label>
            </ProductRegion>
          )}
          {modal === "checkAsset" && assetItem.file !== "original.png" && (
            <label className="checkline">
              <input
                type="checkbox"
                checked={draft.assetMode === "original"}
                onChange={(e) =>
                  patch({
                    assetMode: e.target.checked ? "original" : "processed",
                  })
                }
              />
              使用原图
            </label>
          )}
          {error && <p className="error">{error}</p>}
          <div className="modalfoot">
            {modal === "asset" ? (
              <>
                <button
                  className="dangertext"
                  onClick={() => open("deleteAsset")}
                >
                  <Trash2 size={15} />
                  删除
                </button>
                <button
                  className="primary"
                  onClick={() => {
                    go("home");
                    patch({
                      asset: assetItem.id,
                      identityRegion: null,
                      assetConfirmed: false,
                    });
                    setTimeout(() => open("checkAsset"), 50);
                  }}
                >
                  用于创作
                  <ArrowRight size={15} />
                </button>
              </>
            ) : assetItem.risk ? (
              <button className="primary" onClick={() => pickFile("compose")}>
                更换清晰原图
              </button>
            ) : (
              <button
                className="primary"
                disabled={Boolean(editingVideo && draft.visualDetail && !draft.visualDetail.label.trim())}
                onClick={() => {
                  patch({ assetConfirmed: true });
                  close();
                  tip("已确认素材，可以开始创作");
                }}
              >
                <Check size={16} />
                确认主体与标识完整
              </button>
            )}
          </div>
        </Modal>
      )}
      {modal === "deleteAsset" && (
        <Modal title="删除这张素材？" onClose={close}>
          <p>将从这个工作空间移除「{assetItem.name}」。</p>
          {error && <p className="error">{error}</p>}
          <div className="modalfoot">
            <button className="secondary" onClick={close}>
              保留素材
            </button>
            <button
              className="dangerbtn"
              disabled={!!busy}
              onClick={() =>
                run("delete", async () => {
                  await api("/assets/" + assetItem.id, "DELETE");
                  if (draft.asset === assetItem.id)
                    patch({
                      asset: "",
                      identityRegion: null,
                      assetConfirmed: false,
                    });
                  await refresh();
                  close();
                  tip("素材已删除");
                })
              }
            >
              确认删除
            </button>
          </div>
        </Modal>
      )}
      {modal === "preview" && preview && (
        <Modal title="确认创作方案" onClose={close}>
          <div className="planbox">
            <span className="pill">
              <Sparkles size={13} />
              {formats[preview.kind].name}
            </span>
            <h3>{preview.plan.angle}</h3>
            <p>{draft.brief}</p>
          </div>
          <div className="datarows">
            <div>
              <span>传播目标</span>
              <b>{preview.plan.goal}</b>
            </div>
            <div>
              <span>推测受众</span>
              <b>{preview.plan.audience}</b>
            </div>
            <div>
              <span>交付格式</span>
              <b>
                {preview.kind === "video"
                  ? ratios[preview.ratio] + " · 9 秒 MP4"
                  : preview.kind === "poster"
                    ? ratios[preview.ratio] + " · PNG + 文案"
                    : "TXT 文案"}
              </b>
            </div>
            {preview.kind !== "copy" && preview.plan.output && (
              <div>
                <span>导出精度</span>
                <b>
                  {preview.plan.output.width} × {preview.plan.output.height} px
                  {preview.kind === "poster"
                    ? " · " + preview.plan.output.dpi + " DPI"
                    : " · 24 fps"}
                </b>
              </div>
            )}
            {preview.plan.design && (
              <>
                <div>
                  <span>视觉方案</span>
                  <b>{preview.plan.design.name}</b>
                </div>
                <div>
                  <span>成品配字</span>
                  <b>
                    {preview.plan.brandType?.name || preview.plan.design.type}
                  </b>
                </div>
              </>
            )}
            <div>
              <span>创作引擎</span>
              <b>{preview.engine}</b>
            </div>
            <div>
              <span>本次用量</span>
              <b className="price">{preview.cost} 体验积分</b>
            </div>
          </div>
          {preview.requiresCopyChoice && <CopyChoices key={preview.quote} quote={preview.quote} value={chosenCopy?.quote === preview.quote ? chosenCopy.token : ""} onChange={setChosenCopy} disabled={!!busy} />}
          <OptimizedBrief
            plan={preview.plan}
            fullPosterPrompt={preview.requiresCopyChoice ? (chosenCopy?.quote === preview.quote && chosenCopy.fullPosterPrompt) : preview.fullPosterPrompt}
          />
          <p className="fineprint">
            当前余额 {data.credits} 积分。作品生成成功后结算，失败可免费重试。
          </p>
          {error && <p className="error">{error}</p>}
          <div className="modalfoot">
            <button className="secondary" onClick={close}>
              返回修改
            </button>
            <button
              disabled={!!busy || data.credits < preview.cost || (preview.requiresCopyChoice && chosenCopy?.quote !== preview.quote)}
              className="primary"
              onClick={() => launch()}
            >
              {busy ? (
                <Busy />
              ) : (
                <>
                  <Sparkles size={15} />
                  确认生成
                </>
              )}
            </button>
          </div>
        </Modal>
      )}
      {modal === "revisionQuote" && revisionQuote && <Modal title="确认修改" onClose={close}>
        {revisionQuote.changes && <article><b>{revisionQuote.changes.title}</b><p>{revisionQuote.changes.body}</p><p>{revisionQuote.changes.cta}</p></article>}
        {revisionQuote.options.length > 0 && <fieldset className="short-options"><legend>没选就用短版，可随时修改</legend>
          {revisionQuote.options.map((text,i)=><label key={i}><input type="radio" name="short-copy" checked={shortChoice===i} onChange={()=>setShortChoice(i)}/>{text}</label>)}</fieldset>}
        <p>本次共 {revisionQuote.cost} 积分，原作品会保留。</p>
        {error && <p role="alert">{error}</p>}
        <div className="modalfoot"><button className="secondary" onClick={close}>取消</button><button className="primary" disabled={!!busy} onClick={()=>launch("revision")}>确认修改</button></div>
      </Modal>}
      {modal === "progress" && (
        <Modal title="正在制作作品" onClose={close}>
          <div className="progressbox">
            <div className="process-icon">
              <Sparkles size={29} />
            </div>
            <h3>把创意整理成成品</h3>
            <p>正在编排文案与画面，并检查导出文件。</p>
            <div className="progressbar">
              <i />
            </div>
          </div>
          <button className="secondary full" onClick={() => go("works")}>
            在我的作品中查看
          </button>
        </Modal>
      )}
      {modal === "jobError" && (
        <Modal title="制作暂时中断" onClose={close}>
          <p>{error}</p>
          <p className="fineprint">生成失败，预占积分已退回。</p>
          <button className="primary" onClick={() => go("works")}>
            查看任务
          </button>
        </Modal>
      )}
      {modal === "credits" && (
        <Modal title="体验积分" onClose={close}>
          <div className="balance">
            <Zap size={23} />
            <b>{data.credits}</b>
            <span>可用积分</span>
          </div>
          <div className="datarows">
            {Object.entries(formats).map(([k, f]) => (
              <div key={k}>
                <span>{f.name}</span>
                <b>{data.prices[k]} 积分 / 次</b>
              </div>
            ))}
          </div>
          <p className="fineprint">
            修改作品前会显示本次总积分。主题推荐与预览免费。
          </p>
          <details><summary>任务积分记录</summary>{data.reservations.map((r,i)=><p key={i}>
            {({reserve:"预占",consume:"结算",release:"失败退回"})[r.action]} {r.amount} 积分 · {dateText(r.created)} · {r.job.slice(0,8)}
          </p>)}</details>
          <MerchantShop />
          <h4>积分明细</h4>
          <div className="transactions">
            {data.ledger.map((l, i) => (
              <div key={i}>
                <span>
                  {l.note}
                  <small>{dateText(l.created)}</small>
                </span>
                <b>
                  {l.delta > 0 ? "+" : ""}
                  {l.delta}
                </b>
              </div>
            ))}
          </div>
        </Modal>
      )}
      {modal === "account" && (
        <Modal title="商家账号" onClose={close}>
          {data.login ? (
            <>
              <p>
                当前账号 <b>{data.login}</b>，店铺资料与创作历史已绑定。
              </p>
              <button
                className="secondary"
                onClick={() =>
                  run("logout", async () => {
                    await api("/account/logout", "POST", {});
                    sessionStorage.removeItem("trupic-draft");
                    location.href = location.pathname;
                    location.reload();
                  })
                }
              >
                <LogOut size={15} />
                退出账号
              </button>
            </>
          ) : (
            <>
              <div className="detailtabs">
                <button
                  className={accountMode === "register" ? "sel" : ""}
                  onClick={() => setAccountMode("register")}
                >
                  绑定当前工作室
                </button>
                <button
                  className={accountMode === "login" ? "sel" : ""}
                  onClick={() => setAccountMode("login")}
                >
                  登录已有账号
                </button>
              </div>
              <p>
                {accountMode === "register"
                  ? "创建账号后，可在其他浏览器继续使用当前作品和积分。"
                  : "登录后会切换至该账号的作品、素材和商家档案。"}
              </p>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  run("account", async () => {
                    await api("/account/" + accountMode, "POST", {...auth, ...promotionSource()});
                    clearPromotionSource();
                    const d = await refresh();
                    setProfile(d.profile);
                    if (accountMode === "login") {
                      setDraft(initialDraft);
                      go("home");
                    }
                    close();
                    tip("账号已就绪");
                  });
                }}
              >
                <label className="field">
                  账号
                  <input
                    required
                    autoComplete="username"
                    maxLength={64}
                    value={auth.login || ""}
                    onChange={(e) =>
                      setAuth({ ...auth, login: e.target.value })
                    }
                  />
                </label>
                <label className="field">
                  密码
                  <input
                    type="password"
                    required
                    minLength={8}
                    maxLength={160}
                    autoComplete={
                      accountMode === "register"
                        ? "new-password"
                        : "current-password"
                    }
                    placeholder="至少 8 位"
                    value={auth.password}
                    onChange={(e) =>
                      setAuth({ ...auth, password: e.target.value })
                    }
                  />
                </label>
                {error && <p className="error">{error}</p>}
                <button className="primary full" disabled={!!busy}>
                  {accountMode === "register" ? "绑定账号" : "登录工作室"}
                </button>
              </form>
            </>
          )}
        </Modal>
      )}
      {modal === "adminLogin" && (
        <Modal title="进入运营管理" onClose={close}>
          <p>请输入管理密码。它与商家账号密码不同。</p>
          <details className="original">
            <summary>首次登录，不知道管理密码？</summary>
            <p>首次启动会自动生成本机初始密钥，保存在项目数据目录的 <code>admin.key</code> 文件中，默认位置是 <code>.trupic/admin.key</code>。复制文件中的内容到下方即可登录。</p>
            <p>登录后进入「管理密码」，就能设置自己的密码。如果启动时指定了 <code>TRUPIC_ADMIN_KEY</code>，请使用该启动配置中的值。</p>
          </details>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              run("admin", async () => {
                await api("/account/admin", "POST", {
                  password: auth.password,
                });
                setAuth({ password: "" });
                await refresh();
                go("admin");
                close();
              });
            }}
          >
            <label className="field">
              管理密码或初始密钥
              <input
                required
                type="password"
                autoComplete="off"
                value={auth.password}
                onChange={(e) => setAuth({ password: e.target.value })}
              />
            </label>
            {error && <p className="error">{error}</p>}
            <button className="primary full" disabled={!!busy}>
              <LockKeyhole size={16} />
              进入管理台
            </button>
          </form>
        </Modal>
      )}
      {toast && (
        <div role="status" className="toast">
          <CheckCircle2 size={16} />
          {toast}
        </div>
      )}
    </div>
  );
}
function Toolbar({ filters, filter, setFilter, search, setSearch }) {
  return (
    <div className="toolbar">
      <div className="filtertabs">
        {filters.map((f) => (
          <button
            key={f}
            className={filter === f ? "sel" : ""}
            aria-pressed={filter === f}
            onClick={() => setFilter(f)}
          >
            {formats[f]?.name || f}
          </button>
        ))}
      </div>
      <label className="search">
        <Search size={15} />
        <input
          aria-label="搜索"
          placeholder="搜索名称或关键词"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </label>
    </div>
  );
}
function WorkCard({ work: w, onClick }) {
  const I = formats[w.kind].icon;
  return (
    <button className="workcard" onClick={onClick}>
      <div>
        <img src={w.cover} alt={w.title} />
        <span className="case-format">
          <I size={12} />
          {formats[w.kind].name}
        </span>
      </div>
      <h3>{w.title}</h3>
      <small>
        {dateText(w.created)} · V{w.current}
      </small>
    </button>
  );
}
createRoot(document.getElementById("root")).render(<App />);
