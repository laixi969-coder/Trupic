import React, { useEffect, useRef, useState } from "react";
import { ArrowLeft, Check, ClipboardList, Play } from "lucide-react";
import { api } from "./ui.jsx";
import "./blind-review.css";

const root = "/agent/blind-reviews";
const sectors = { food: "餐饮", retail: "零售", service: "到店服务" };
const reasons = ["活动信息不对", "商品看不清", "口播不自然", "卖点没讲清", "不像我们店的口吻"];
const factNames = { amount:"价格", weekday:"活动日期", channel:"适用渠道", currency:"币种", product:"商品", facts:"经营条件" };
const navigate = (id) => { location.hash = id ? "blind-review/" + id : "blind-review"; };

function seconds(value) {
  if (value == null) return "暂无计时";
  const whole = Math.round(value);
  if (whole < 60) return whole + " 秒";
  return Math.floor(whole / 60) + " 分 " + whole % 60 + " 秒";
}

function ReviewResults({ reveal }) {
  const preference = { A: "作品 A", B: "作品 B", tie: "两版都可以", neither: "两版都退回" };
  const revision = reveal.revisionSlot ? reveal.versions[reveal.revisionSlot] : null;
  return <section className="br-results" aria-live="polite">
    <h2>{revision ? "盲选结果" : "首稿评价"}</h2>
    <p className="br-verdict">{revision && <>你的选择是<strong>{preference[reveal.preference]}</strong>。</>}
      {reveal.firstDraftSlot
        ? <>作品 {reveal.firstDraftSlot} 是首稿，你选了<strong>{reveal.firstDraftPublish ? "可以直接发" : "需要修改"}</strong>。</>
        : <>本次比较两个已修改的版本。</>}
    </p>
    {reveal.firstDraftReason && <p>首稿退回原因　{reveal.firstDraftReason}</p>}
    <div className="br-result-grid">{Object.entries(reveal.versions).map(([slot, v]) => <article key={slot}>
      <h3>作品 {slot} · {v.role === "first" ? "首稿" : slot === reveal.baseSlot ? "对照版" : "修改稿"} <small>v{v.version}</small></h3>
      <p>{reveal.ratings[slot].publish ? "可以直接发" : "需要修改"} {reveal.ratings[slot].reason}</p>
      <dl><dt>本次制作实际扣分</dt><dd>{v.credits == null ? "暂无流水" : v.credits + " 积分"}</dd>
        {v.visualEngine && <><dt>画面制作方式</dt><dd>{v.visualEngine}</dd></>}
        {v.modelCharge && <><dt>模型实际费用</dt><dd>{v.modelCharge.amount} {v.modelCharge.currency}</dd></>}
        <dt>需求提出至该版交付</dt><dd>{seconds(v.requestToDeliverySeconds)}</dd>
        <dt>确认制作至交付</dt><dd>{seconds(v.productionSeconds)}</dd></dl>
    </article>)}</div>
    {revision && <p>商家亲自改稿用时　{reveal.merchantEditMinutes == null ? "未填写" : reveal.merchantEditMinutes + " 分钟"}</p>}
    {reveal.factChanges?.length > 0 && <div className="br-facts"><strong>两次交付的活动条件有变化</strong>
      {reveal.factChanges.map(f => <p key={f.field}>{factNames[f.field] || f.field}　{String(f.before ?? "未记录")} → {String(f.after ?? "未记录")}</p>)}
      <p>这次偏好同时受到活动条件和创作表现的影响。</p></div>}
  </section>;
}

export function ReviewBallot({ review, onAnswer, submitting = false, error = "" }) {
  const [ratings, setRatings] = useState({});
  const [preference, setPreference] = useState("");
  const [minutes, setMinutes] = useState("");
  const players = useRef({});
  const pair = review.options.length > 1;
  const reveal = review.reveal;
  const displayed = reveal?.ratings || ratings;
  function rate(slot, changes) {
    setRatings(rows => ({ ...rows, [slot]: { ...rows[slot], ...changes } }));
    if (Object.hasOwn(changes, "publish")) setPreference("");
  }
  const allRated = review.options.every(o => typeof ratings[o.slot]?.publish === "boolean" &&
    (ratings[o.slot].publish || ratings[o.slot]?.reason?.trim()));
  const preferences = [
    ["A", "作品 A", ratings.A?.publish], ["B", "作品 B", ratings.B?.publish],
    ["tie", "两版都可以", ratings.A?.publish && ratings.B?.publish],
    ["neither", "两版都退回", ratings.A?.publish === false && ratings.B?.publish === false],
  ];
  function submit(e) {
    e.preventDefault();
    if (!allRated || (pair && !preference) || submitting) return;
    const answers = Object.fromEntries(review.options.map(({ slot }) => [slot,
      { publish: ratings[slot].publish, reason: ratings[slot].publish ? "" : ratings[slot].reason.trim() }]));
    onAnswer({ ratings: answers, preference: pair ? preference : null,
      merchantEditMinutes: pair && minutes !== "" ? Number(minutes) : null });
  }
  return <div className="br-ballot">
    <header className="br-case-title"><p>{review.brief.sectorLabel} · {review.source === "demo" ? "演示评审" : "商家评审"}</p>
      <h1>{review.brief.title}</h1><p>{review.brief.reviewerPrompt || review.brief.goal}</p>
    </header>
    <form onSubmit={submit}>
      <div className={'br-samples' + (pair ? '' : ' br-single')}>{review.options.map(({slot, url}) => {
        const row = displayed[slot] || {};
        return <section key={slot} className="br-sample" aria-label={"作品 " + slot}>
          <h2>作品 {slot}</h2>
          {review.kind === "video" ? <video ref={el => { players.current[slot] = el; }} src={url} preload="metadata"
            controls playsInline aria-label={"播放作品 " + slot}
            onPlay={() => Object.entries(players.current).forEach(([id, el]) => { if (id !== slot) el?.pause(); })} />
            : review.kind === "poster" ? <img src={url} alt={"待评海报 " + slot} /> : <CopySample url={url} />}
          {!reveal && <fieldset><legend>这份作品，你愿意直接发吗？</legend>
            <div className="br-options">{[[true,"可以直接发"], [false,"需要修改"]].map(([publish,label]) =>
              <button type="button" aria-pressed={row.publish === publish} key={label} disabled={submitting}
                onClick={() => rate(slot, {publish})}>{label}</button>)}</div>
            {row.publish === false && <div className="br-reason">
              <label>退稿原因<textarea value={row.reason || ""} required maxLength={400} disabled={submitting}
                onChange={e => rate(slot, {reason:e.target.value})} placeholder="指出要改的一处，或选择下方原因" /></label>
              <div className="br-tags">{reasons.map(r => <button type="button" disabled={submitting} key={r}
                onClick={() => rate(slot, {reason:r})}>{r}</button>)}</div>
            </div>}
          </fieldset>}
        </section>;
      })}</div>
      {!reveal && <div className="br-submit">
        {pair && <><fieldset><legend>如果现在发布，你会选哪版？</legend>
          <div className="br-options">{preferences.map(([value,label,can]) => <button key={value} type="button"
            aria-pressed={preference === value} disabled={submitting || !allRated || !can} onClick={() => setPreference(value)}>{label}</button>)}</div>
        </fieldset><label className="br-time">你亲自参与改稿用了几分钟？ <small>选填，可填 0</small>
          <input type="number" min="0" step="any" value={minutes} disabled={submitting} onChange={e => setMinutes(e.target.value)} /></label></>}
        {error && <p role="alert">{error}</p>}
        <button className="br-primary" type="submit" disabled={submitting || !allRated || (pair && !preference)}>
          <Check size={17}/>{submitting ? "正在保存…" : "提交并揭晓"}</button>
      </div>}
    </form>
    {reveal && <ReviewResults reveal={reveal}/>}
  </div>;
}

function CopySample({url}) {
  const [text, setText] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    fetch(url,{signal:controller.signal}).then(r => { if (!r.ok) throw Error(); return r.text(); })
      .then(setText).catch(() => { if (!controller.signal.aborted) setText("文案未能载入，请刷新重试。"); });
    return () => controller.abort();
  },[url]);
  return <div className="br-copy">{text}</div>;
}

function ReviewIndex({preselected, onStart, onUse, submitting}) {
  const [data, setData] = useState(null), [error, setError] = useState("");
  const [sector, setSector] = useState("food"), [briefId, setBrief] = useState("food-01");
  const [work, setWork] = useState(preselected?.work || ""), [version, setVersion] = useState(preselected?.version || 0);
  const [chosenBase, setChosenBase] = useState(0);
  useEffect(() => {
    let live = true;
    Promise.all([api("/agent/blind-briefs"), api("/agent/blind-candidates"), api(root)]).then(([br, works, reviews]) => {
      if (!live) return;
      setData({briefs:br.briefs, candidates:works.candidates, ...reviews});
      const current = works.candidates.find(w => w.work === preselected?.work);
      if (current) {
        setWork(current.work); setVersion(preselected.version || current.versions.at(-1));
        const associated=br.briefs.find(b => b.id === current.briefId);
        if (associated) { setBrief(associated.id); setSector(associated.sector); }
      }
    }).catch(e => { if (live) setError(e.message); }); return () => { live = false; };
  },[preselected]);
  const group = data?.briefs.filter(b => b.sector === sector) || [];
  const brief = group.find(b => b.id === briefId) || group[0];
  const candidate = data?.candidates.find(c => c.work === work);
  const earlier = candidate?.versions.filter(n => n < version) || [];
  const base = earlier.includes(chosenBase) ? chosenBase : earlier.at(-1) || 1;
  function chooseSector(key) { setSector(key); setBrief(data.briefs.find(b => b.sector===key)?.id || ""); }
  return <div className="br-index"><header className="br-case-title"><h1>商家盲评</h1><p>用已交付的作品评价首稿，或并排盲选同一作品的两个版本。盲评免费。</p></header>
    {error && <p role="alert">{error}</p>}
    {!data && !error && <p role="status">正在读取简报和作品…</p>}
    {data && <>
      <section className="br-index-panel"><h2>选择评审简报</h2>
        <div className="br-options">{Object.entries(sectors).map(([id,label]) =>
          <button key={id} type="button" aria-pressed={sector===id} onClick={() => chooseSector(id)}>{label} · {data.briefs.filter(b=>b.sector===id).length}</button>)}</div>
        <label>简报<select value={brief?.id || ""} onChange={e=>setBrief(e.target.value)}>
          {group.map(b=><option value={b.id} key={b.id}>{b.title}</option>)}</select></label>
        {brief && <div className="br-brief"><strong>{brief.title}</strong><p>{brief.brief}</p><p>{brief.assetNote}</p>
          <details><summary>经营事实与创作限制</summary><p>{brief.facts.product} · {brief.facts.offer}</p>
            <p>{brief.facts.conditions.join("；")}</p><p>避免使用　{brief.avoid.join("；")}</p></details>
          <small>Trupic 编写的试评简报，使用前请核对本店资料。</small>
          <button type="button" onClick={()=>onUse(brief)}>带入营销助理创作</button></div>}
        <h2>选择本店作品</h2>
        {data.candidates.length ? <><label>作品<select value={work} onChange={e=>{
          const selected = data.candidates.find(c=>c.work===e.target.value);
          setWork(e.target.value); setVersion(selected?.versions.at(-1) || 0); setChosenBase(0);
          const associated=data.briefs.find(b=>b.id === selected?.briefId);
          if (associated) { setBrief(associated.id); setSector(associated.sector); }
        }}><option value="">请选择已有交付</option>{data.candidates.map(w=><option value={w.work} key={w.work}>{w.title}</option>)}</select></label>
        {candidate && <label>待评版本<select value={version} onChange={e=>{setVersion(Number(e.target.value)); setChosenBase(0);}}>
          {candidate.versions.map(n=><option key={n} value={n}>{n===1 ? "只评首稿" : "版本 " + n}</option>)}</select></label>}
        {earlier.length > 0 && <label>对照版本<select value={base} onChange={e=>setChosenBase(Number(e.target.value))}>
          {earlier.map(n=><option key={n} value={n}>{n===1 ? "版本 1（首稿）" : "版本 " + n}</option>)}</select></label>}
        <button className="br-primary" disabled={submitting || !brief || !work || !version}
          onClick={()=>onStart({briefId:brief.id,work,baseVersion:base,revisionVersion:version})}><Play size={16}/>进入匿名评审</button></>
          : <p>交付第一份作品后，就可以记录是否愿意直接发布。</p>}
      </section>
      <section className="br-index-panel"><h2>本店评审记录</h2>
        {data.summary && <p>已回应 {data.summary.answered} / {data.summary.issued} 次。符合统计条件的首稿中，{data.summary.firstDraftPublish} / {data.summary.firstDraftResponses} 份可直接发。</p>}
        {data.summary?.issued > 0 && <details><summary>按行业看回应与首稿采纳</summary>
          {Object.entries(data.summary.bySector).map(([key,s])=><p key={key}>{sectors[key]}　回应 {s.answered} / {s.issued} 次，首稿可直接发 {s.firstDraftPublish} / {s.firstDraftResponses} 份。</p>)}
          <p>活动条件变化的回顾评价和演示账户的答卷均单独记录。</p></details>}
        {data.reviews.length ? <ul>{data.reviews.map(r=><li key={r.id}><a href={"#blind-review/"+r.id}>{data.briefs.find(b=>b.id===r.briefId)?.title || r.briefId}
          <span>{r.source === "demo" ? "演示 · " : ""}{r.status==="submitted" ? "查看结果" : "继续盲评"}</span></a></li>)}</ul> : <p>尚无评审记录。</p>}
      </section>
    </>}
  </div>;
}

export default function BlindWorkspace({caseId,preselected,onUse}) {
  const [review,setReview]=useState(null),[error,setError]=useState(""),[busy,setBusy]=useState(false);
  useEffect(()=>{
    if (!caseId) return;
    let live=true; api(root+"/"+encodeURIComponent(caseId)).then(value=>{if(live)setReview(value);})
      .catch(e=>{if(live)setError(e.message);}); return ()=>{live=false;};
  },[caseId]);
  async function answer(payload) {
    setBusy(true);setError("");
    try { setReview(await api(root+"/"+encodeURIComponent(caseId)+"/answer","POST",payload)); }
    catch(e) { setError(e.message); } finally {setBusy(false);}
  }
  async function start(payload) {
    setBusy(true);setError("");
    try { const value=await api(root,"POST",payload);navigate(value.id); } catch(e){setError(e.message);} finally {setBusy(false);}
  }
  return <main className="br-page"><nav className="br-nav"><a href={caseId ? "#blind-review" : "#home"}><ArrowLeft size={18}/>{caseId ? "评审列表" : "营销助理"}</a><span><ClipboardList size={17}/>商家盲评</span></nav>
    {caseId ? (review ? <ReviewBallot review={review} onAnswer={answer} submitting={busy} error={error}/> : <p role="status">{error || "正在打开匿名作品…"}</p>) :
      <><ReviewIndex preselected={preselected} onStart={start} onUse={onUse} submitting={busy}/>{error && <p role="alert">{error}</p>}</>}
  </main>;
}
