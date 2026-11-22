import React, { useEffect, useRef, useState } from "react";
import { UploadCloud, Sparkles, ArrowRight, RefreshCw, Download, X } from "lucide-react";
import { api, Modal, Busy, dateText } from "./ui.jsx";

const statusText = { queued: "等待制作", running: "正在制作", failed: "制作中断", complete: "已完成" };

export default function AutoCreate({ assets, draft, patch, refresh, textRef, checkAsset, options }) {
  const facts = draft.extraFacts || "";
  const setFacts = (extraFacts) => patch({ extraFacts });
  const [plan, setPlan] = useState(null);
  const [planning, setPlanning] = useState(false);
  const [planVersion, setPlanVersion] = useState(0);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [runs, setRuns] = useState([]);
  const [zoom, setZoom] = useState(null);
  const [copied, setCopied] = useState("");
  const [submitted, setSubmitted] = useState("");
  const fileRef = useRef();
  const keyRef = useRef("");
  const lock = useRef(false);
  const progress = useRef("");
  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;
  const selected = assets.find((asset) => asset.id === draft.asset);

  useEffect(() => {
    let active = true, timer;
    async function poll() {
      try {
        const rows = await api("/creations");
        if (!active) return;
        setRuns(rows);
        if (rows.some((row) => row.requestKey === keyRef.current)) setSubmitted(keyRef.current);
        const next = rows.flatMap((row) => row.items.map((item) => item.job + item.state)).join();
        if (progress.current && next !== progress.current) await refreshRef.current();
        progress.current = next;
      } catch (e) {
        if (active) setError(e.message);
      }
      if (active) timer = setTimeout(poll, 2000);
    }
    poll();
    return () => { active = false; clearTimeout(timer); };
  }, []);

  const request = JSON.stringify({
    brief: draft.brief, asset: draft.asset, facts, assetConfirmed: draft.assetConfirmed,
    assetMode: draft.assetMode, identityRegion: draft.identityRegion, topicId: draft.topicId,
    reference: draft.reference, source: draft.source, posterStyle: draft.posterStyle,
    fontId: draft.fontId, lettering: draft.lettering,
  });

  useEffect(() => {
    let active = true;
    setPlan(null);
    setError("");
    if (draft.brief.trim().length < 2) {
      setPlanning(false);
      return;
    }
    const signature = JSON.stringify([request, planVersion]);
    let saved;
    try { saved = JSON.parse(sessionStorage.getItem("trupic-auto-request") || "null"); } catch {}
    keyRef.current = saved?.signature === signature ? saved.key : crypto.randomUUID();
    try { sessionStorage.setItem("trupic-auto-request", JSON.stringify({ signature, key: keyRef.current })); } catch {}
    setPlanning(true);
    const timer = setTimeout(async () => {
      try {
        const result = await api("/creations/plan", "POST", JSON.parse(request));
        if (active) setPlan({ ...result, request, expires: Date.now() + 25 * 60 * 1000 });
      } catch (e) {
        if (active) setError(e.message);
      } finally {
        if (active) setPlanning(false);
      }
    }, 500);
    return () => { active = false; clearTimeout(timer); };
  }, [request, planVersion]);

  async function perform(label, action) {
    if (lock.current) return;
    lock.current = true;
    setBusy(label); setError("");
    try { await action(); } catch (e) { setError(e.message); }
    finally { lock.current = false; setBusy(""); }
  }
  async function upload(e) {
    const file = e.target.files?.[0]; e.target.value = "";
    if (!file) return;
    await perform("upload", async () => {
      if (file.size > 12 * 1024 * 1024) throw new Error("请选择小于 12 MB 的图片。");
      const body = new FormData(); body.append("image", file);
      const asset = await api("/assets", "POST", body);
      await refreshRef.current();
      selectAsset(asset.id);
    });
  }
  function selectAsset(asset) {
    patch({ asset, assetMode: "processed", assetConfirmed: false, identityRegion: null, extraFacts: "" });
  }
  async function create(e) {
    e?.preventDefault();
    if (!plan?.ready || plan.request !== request || planning || submitted === keyRef.current) return;
    if (Date.now() > plan.expires) { setPlanVersion((v) => v + 1); return; }
    await perform("create", async () => {
      const row = await api("/creations", "POST", { quote: plan.quote, confirmedCost: plan.cost, requestKey: keyRef.current });
      setRuns((current) => [row, ...current.filter((r) => r.id !== row.id)]);
      setSubmitted(keyRef.current);
      await refreshRef.current();
    });
  }
  async function retry(job) {
    await perform(job, async () => {
      await api("/jobs/" + job + "/retry", "POST", {});
      setRuns(await api("/creations"));
    });
  }

  return <>
    <section className="auto-create" aria-label="一键创作">
      <div className="auto-heading"><Sparkles size={20} /><h2>说说你想怎么推广</h2></div>
      <p className="auto-description">一句需求，自动完成配文、画面和需要的短片。</p>
      <form onSubmit={create}>
        <div className="auto-inputs">
          <div className="auto-source">
            {selected ? <><img src={selected.original} alt={selected.name} /><span>{selected.name}</span><button type="button" className="textbtn" disabled={!!busy} onClick={() => { selectAsset(""); }}><X size={14} />移除商品图</button><button type="button" className="textbtn" onClick={() => checkAsset(selected)}>核对商品素材</button></> : <button type="button" className="auto-upload" onClick={() => fileRef.current?.click()} disabled={!!busy}><UploadCloud size={30} /><strong>添加商品图（选填）</strong><span>JPG、PNG、WebP · 最大 12 MB</span></button>}
            <input ref={fileRef} type="file" aria-label="上传商品图" accept="image/jpeg,image/png,image/webp" onChange={upload} hidden />
            {!!assets.length && <details className="auto-library"><summary>从素材库选择</summary><select aria-label="选择已有商品图" value={draft.asset} disabled={!!busy} onChange={(e) => { selectAsset(e.target.value); }}><option value="">选择一张商品图</option>{assets.map((asset) => <option key={asset.id} value={asset.id} disabled={asset.risk}>{asset.name}{asset.risk ? "（请更换清晰图片）" : ""}</option>)}</select></details>}
          </div>
          <label className="auto-brief">你想做什么？<textarea ref={textRef} required maxLength={1200} disabled={!!busy} value={draft.brief} onChange={(e) => patch({ brief: e.target.value, source: "一键创作", topicId: "", reference: "" })} onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === "Enter") create(e); }} placeholder="例如：春山抹茶粉新品上市，100g/罐，48元/罐，可搭配牛奶。帮我做一套上新图片，再配一条9秒短视频。" /></label>
        </div>
        {options}
        {(plan?.questions?.length > 0 || facts) && <div className="auto-questions"><p>{plan?.message || "补充商品信息"}</p>{plan?.questions?.map((question) => <p key={question}>{question}</p>)}<label>补充信息<textarea value={facts} maxLength={400} disabled={!!busy} onChange={(e) => setFacts(e.target.value)} placeholder="把实际价格、日期或适用条件写在这里" /></label></div>}
        <div className="auto-plan" role="status" aria-live="polite">
          {busy === "upload" ? "正在检查图片…" : planning ? "正在理解需求、安排成品…" : plan?.ready ? <><strong>将为你制作：{plan.deliveries.map((item) => item.label).join("、")}</strong><span>{plan.cost} 积分 · 每项成功交付后结算</span></> : <span>{plan?.message || "写下想推广的商品或服务。"}</span>}
        </div>
        {error && <p className="error" role="alert">{error} <button className="textbtn" type="button" disabled={!!busy} onClick={() => setPlanVersion((v) => v + 1)}>重新检查需求</button></p>}
        <div className="auto-footer"><small>保留商品原貌；缺少关键资料时会先提醒你。</small><button className="primary" disabled={!!busy || planning || !plan?.ready || plan.request !== request || submitted === keyRef.current}>{busy === "create" ? <Busy text="开始制作" /> : submitted === keyRef.current && plan?.ready ? "已开始 · 修改需求可再创作" : <><Sparkles size={16} />一键创作<ArrowRight size={16} /></>}</button></div>
      </form>
    </section>
    {!!runs.length && <section className="auto-results" aria-label="创作结果"><h2>你的创作</h2>{runs.map((run) => <article className="auto-run" key={run.id}>
      <header><div><small>{dateText(run.created)}</small><h3>{run.title}</h3><p>{run.brief}</p></div>{run.complete ? <a className="primary" href={run.download} download><Download size={15} />整套下载</a> : <span role="status">{run.items.filter((item) => item.state === "complete").length} / {run.items.length} 项完成{run.active ? " · 正在制作" : " · 有项目需要重试"}</span>}</header>
      <div className="auto-deliveries">{run.items.map((item) => <section className={"auto-delivery " + (item.kind === "copy" ? "auto-copy" : "")} key={item.job}>
        <h4>{item.label}</h4>
        {item.text ? <p className="auto-copy-text">{item.text}</p> : item.preview ? <button type="button" className="bundle-image" onClick={() => setZoom(item)} aria-label={"预览" + item.label}><img src={item.preview} alt={item.label} />{item.video && <span className="auto-video-tag">▶ 播放短片</span>}</button> : <div className="bundle-placeholder" role="status">{statusText[item.state]}</div>}
        {item.error && <p role="alert" className="error">{item.error}</p>}
        <div className="auto-item-actions">{item.text && <button className="textbtn" type="button" onClick={() => perform("copy", async () => { await navigator.clipboard.writeText(item.text); setCopied(item.job); })}>{copied === item.job ? "已复制" : "复制文案"}</button>}{item.download && <><a href={item.download} download>下载此项</a><a href={"#work/" + item.work}>查看建议与版本</a></>}{item.state === "failed" && <button className="secondary" disabled={!!busy} onClick={() => retry(item.job)}><RefreshCw size={14} />重试此项</button>}</div>
      </section>)}</div>
      <details className="auto-facts"><summary>核对本次商品资料</summary><p>{run.summary.facts.join("；") || "未补充商品参数，成品未新增规格与价格。"}</p>{run.summary.notes.map((note) => <p key={note}>{note}</p>)}</details>
    </article>)}</section>}
    {zoom && <Modal title={zoom.label} onClose={() => setZoom(null)} wide>{zoom.video ? <video className="bundle-zoom" controls autoPlay playsInline src={zoom.video} /> : <img className="bundle-zoom" src={zoom.preview} alt={zoom.label} />}</Modal>}
  </>;
}
