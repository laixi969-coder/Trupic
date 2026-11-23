import React, { useEffect, useRef, useState } from "react";
import { api, Field } from "./ui.jsx";

const kinds = [["text", "策划与文案"], ["image", "图片生成"], ["video", "视频生成"], ["edit","图片编辑"], ["vision", "商品与成品视觉审核"]];
const categories = [["text", "文字类"], ["image", "图片类"], ["vision", "图片审核类"], ["video", "视频生成类"]];
const descriptions = {edit:"按商家要求编辑框选区域。",text: "写标题、卖点和短片脚本，只需要文本模型。", image: "生成图片环境，商品原图与准确文案在本地合成。", video: "生成动态环境，再合成商品原图、三镜字幕和配乐。", vision: "接收图片，检查商品与成品；不是图片生成模型。"};
const localLabels = {edit:"本地明暗调整",text:"本地文案规则",image:"本地商品排版",video:"本地镜头运动",vision:"本地像素与文字检查"};

function eligibleModels(catalog, kind) {
  return (catalog?.models || []).filter(model => !model.known || model.kinds.includes(kind));
}

function Connection({ kind, platform, busy, act, routeVersion, formal }) {
  const configured = platform.connections[kind];
  const [form, set] = useState({
    id: platform.id, label: platform.label, capability: kind, baseUrl: configured.baseUrl || "", key: "",
    model: configured.model || "",
  });
  const [catalog, setCatalog] = useState(configured.catalog || null);
  const [syncing,setSyncing] = useState(false);
  const [err,setError] = useState("");
  const [probe,setProbe] = useState(null);
  const [probeBusy,setProbeBusy] = useState(false);
  const [pollAttempt,setPollAttempt] = useState(0);
  const [metadata,setMetadata] = useState({});
  const [reviewed,setReviewed] = useState("");
  const tested = useRef("");
  const fingerprint = JSON.stringify(form);
  useEffect(() => {
    if (!probe?.id || !["queued","running"].includes(probe.state)) return;
    let active = true, timer;
    async function poll() {
      try {
        const next = await api("/admin/probes/"+probe.id);
        if (!active) return;
        setProbe(next);
        if (["queued","running"].includes(next.state)) timer=setTimeout(poll,1500);
        else setProbeBusy(false);
      } catch(e) { if(active) {setError(e.message);setProbeBusy(false);} }
    }
    poll();
    return ()=>{active=false;clearTimeout(timer);};
  },[probe?.id,probe?.state,pollAttempt]);
  const locked = busy || syncing || probeBusy;
  const base = form.baseUrl.trim().replace(/\/+$/, "");
  const sameBase = base === configured.baseUrl;
  const savedKey = sameBase && configured.hasKey;
  let local = false;
  try { local = ["localhost", "127.0.0.1", "[::1]"].includes(new URL(base).hostname); } catch {}
  const canSync = base && (form.key.trim() || savedKey || local || (sameBase && configured.model));
  const options = eligibleModels(catalog, kind);
  const selectedModel = options.find(option => option.id === form.model);
  const selected = !!selectedModel;

  function changeConnection(name, value) {
    set({...form, [name]: value, model: ""});
    setCatalog(null);
    setProbe(null);
    setError("");
  }
  async function sync() {
    setSyncing(true);
    setError("");
    try {
      const latest = await api("/admin/sync-models", "POST", form);
      setCatalog(latest);
      if (!eligibleModels(latest, kind).some(option => option.id === form.model)) {
        set({...form, model: ""});
        setProbe(null);
      }
    } catch (e) { setError(e.message); }
    finally { setSyncing(false); }
  }
  async function test() {
    const retry=probe?.id&&probe.state!=="complete"&&tested.current===fingerprint;
    if (!retry) setProbe(null);
    setProbeBusy(true);setError("");tested.current=fingerprint;
    try {setProbe(await api(retry ? "/admin/probes/"+probe.id+"/retry" : "/admin/probes","POST",form));setPollAttempt(n=>n+1);}
    catch(e) {setError(e.message);setProbeBusy(false);}
  }
  async function save(e) {
    e.preventDefault();
    if (locked || !selected) return;
    if (await act("model-platform", {...form, activate: true, expectedVersion: routeVersion})) {
      const saved = {...form, baseUrl: base, key: ""};
      if (tested.current === fingerprint) tested.current = JSON.stringify(saved);
      if (reviewed === fingerprint) setReviewed(JSON.stringify(saved));
      set(saved);
    }
  }
  return <form className="formpanel integration" onSubmit={save}>
    <h2>{platform.label}</h2>
    {platform.id.startsWith("custom-") && <Field label="平台名称" name="label" form={form} set={set} limit={60} />}
    <small>{kinds.find(([id]) => id === kind)[1]}{configured.model && " · 已保存 " + configured.model}</small>
    <label className="field">Base URL<input type="url" required maxLength={1200} disabled={locked}
      placeholder="https://api.example.com/v1" value={form.baseUrl}
      onChange={e => changeConnection("baseUrl", e.target.value)} /></label>
    <label className="field">API Key<input type="password" autoComplete="new-password" maxLength={2400}
      disabled={locked} value={form.key} placeholder={savedKey ? "已保存，留空沿用" : local ? "本机服务可留空" : "输入平台密钥"}
      onChange={e => changeConnection("key", e.target.value)} /></label>
    <div className="model-tests"><button type="button" className="secondary" disabled={locked || !canSync}
      onClick={sync}>{syncing ? "正在同步…" : "同步最新模型"}</button>
      {catalog && <small>上次同步 {new Date(catalog.updated).toLocaleString()}</small>}</div>
    {catalog && base.startsWith("https://api.atlascloud.ai/") && <small>已同步 Atlas 公开模型目录。选择模型后，测试连接可验证 API Key 和调用权限。</small>}
    <label className="field">模型<select aria-label="模型" value={selected ? form.model : ""} disabled={locked || !options.length}
      onChange={e => {set({...form, model: e.target.value}); setError("");}}>
      <option value="">{!catalog ? "请先同步最新模型" : options.length ? "请选择模型" : "暂无已核实发布日期的可用模型"}</option>
      {options.map(option => <option key={option.id} value={option.id}>{option.id} · {option.priceLabel || "平台未提供价格"}</option>)}
    </select></label>
    {configured.model && configured.selectable === false && <p className="fineprint">当前已保存模型尚未通过发布日期筛选，请选择已核实的模型。</p>}
    <small>仅显示已核实于 2026-01-01 及以后发布的模型。
      {catalog?.hiddenUnknown > 0 && ` 已隐藏 ${catalog.hiddenUnknown} 个发布日期待核实的模型。`}
      {catalog?.hiddenOlder > 0 && ` 已排除 ${catalog.hiddenOlder} 个早期模型。`}</small>
    {selectedModel && <div className="connection-result">
      <p>发布日期 {selectedModel.released}</p>
      <p>{selectedModel.priceLabel || "平台未提供价格"}</p>
      {selectedModel.priceNote && <small>{selectedModel.priceNote}</small>}
      <p><a href={selectedModel.releaseSource} target="_blank" rel="noreferrer">发布依据</a>
        {selectedModel.priceSource && <> · <a href={selectedModel.priceSource} target="_blank" rel="noreferrer">平台价格</a></>}</p>
    </div>}
    <div className="model-tests"><button type="button" className="secondary" disabled={locked || !selected}
      onClick={test}>{probeBusy ? "正在测试…" : "测试连接"}</button>
      <button className="primary" disabled={locked || !selected}>保存并启用</button></div>
    {["image", "edit", "video"].includes(kind) && <small>测试将实际生成素材，并计入平台用量。</small>}
    {(formal || probe?.state === "complete") && <details><summary>正式模型核验 · {(configured.approved && configured.model===form.model && sameBase && !form.key) || reviewed===fingerprint ? "已核验" : "待核验"}</summary>
      {[["released","发布日期","date"],["source","官方发布依据","url"],["family","模型系列","text"],["version","核实版本","text"],["minimum","系列最低版本","text"],["review","实际输出质量与成本核验记录","text"]].map(([k,l,type])=>
        <label className="field" key={k}>{l}<input type={type} value={metadata[k]||""} onChange={e=>setMetadata({...metadata,[k]:e.target.value})}/></label>)}
      <button type="button" className="secondary" disabled={probe?.state!=="complete"||tested.current!==fingerprint} onClick={async()=>{
        try {await api("/admin/model-admission","POST",{...form,...metadata,probe:probe.id});setReviewed(fingerprint);setError("");} catch(e){setError(e.message);}
      }}>核准此连接与系列门槛</button></details>}
    {err&&<p className="error" role="alert">{err}</p>}
    {probe && tested.current===fingerprint && <div className="connection-result" role="status"><strong>{probe.state==="complete"?"连接测试通过":probe.state==="failed"?"连接测试失败":"正在等待平台返回"}</strong><p>{probe.model} · {probe.message||probe.error||"测试在后台执行，完成后将在此显示结果。"}{probe.ms!=null&&" · "+(probe.ms/1000).toFixed(1)+" 秒"}</p>{probe.preview&&(kind==="video"?<video src={probe.preview} muted controls style={{maxWidth:"100%",maxHeight:360}} />:<img src={probe.preview} alt="接口实际返回的测试图" style={{maxWidth:"100%",maxHeight:360}} />)}</div>}
  </form>;
}

function ProviderCosts({ costs, act, busy }) {
  const initial = { day: new Date().toISOString().slice(0,10), kind:"text", currency:"CNY" };
  const [bill, setBill] = useState(initial);
  return <details className="formpanel"><summary>模型预算与账单</summary>
    <p>{costs.limit == null ? "当前未设置每日金额上限。" : `今日已预留 ${costs.reserved} / ${costs.limit} 元（UTC）。`}</p>
    <form onSubmit={async e => {e.preventDefault(); if (await act("provider-bill",bill)) setBill(initial);}}>
      <p>按供应商账单录入当日合计。同日、平台、模型、用途及币种相同的记录可重新核对。</p>
      <label className="field">账单日期（UTC）<input type="date" required value={bill.day} onChange={e => setBill({...bill,day:e.target.value})}/></label>
      <label className="field">用途<select value={bill.kind} onChange={e => setBill({...bill,kind:e.target.value})}>{kinds.map(([id,label]) => <option key={id} value={id}>{label}</option>)}</select></label>
      {[["platform","平台",80],["model","模型",180],["currency","币种代码",3],["amount","账单金额",30],["source","账单编号或核对来源",220]].map(([key,label,size]) => <Field key={key} name={key} label={label} limit={size} required form={bill} set={setBill} />)}
      <button className="secondary" disabled={busy}>保存核对金额</button>
    </form>
    {costs.bills.map(b => <p key={JSON.stringify([b.day,b.platform,b.model,b.kind,b.currency])}>{b.day} · {b.platform} / {b.model} · {kinds.find(([id])=>id===b.kind)?.[1]} · {b.amount} {b.currency} · {b.source}</p>)}
  </details>;
}

function Routing({config,busy,act}) {
  const {platforms,routes} = config;
  const [selection,select] = useState(Object.fromEntries(kinds.map(([k])=>[k,routes[k]||""])));
  const [backups,setBackups] = useState(config.backups || {});
  return (
    <form className="formpanel integration" onSubmit={e=>{e.preventDefault();act("model-routes",{...selection,backups,expectedVersion:config.routeVersion});}}>
      <h2>按能力选择调用平台</h2>
      {config.routeVersion > 0 && <small>当前路由版本 V{config.routeVersion}</small>}
      <p>所有创作模型统一在这里配置。每项能力可以来自不同平台，各自使用独立的 API 地址、模型和密钥。</p>
      <div className="capability-grid">{kinds.map(([k,label])=><label className="field capability-card" key={k}><strong>{label}</strong><small>{descriptions[k]}</small><select aria-label={label+"调用连接"} value={selection[k]} onChange={e=>{
        const value=e.target.value;
        select({...selection,[k]:value});
        if (!value || value==="local-rules" || value===backups[k]) setBackups({...backups,[k]:""});
      }}>
        <option value="">{!config.formal&&config.defaults?.[k]?.model ? "已有配置 · "+config.defaults[k].model : localLabels[k]+"（默认）"}</option>
        {(config.defaults?.[k]?.model || selection[k]==="local-rules") && <option value="local-rules">{localLabels[k]}</option>}
        {platforms.filter(p=>p.supported.includes(k)&&p.connections[k]?.model&&p.connections[k].selectable&&(!config.formal||p.connections[k].approved)).map(p=><option value={p.id} key={p.id}>{p.label} · {p.connections[k].model}</option>)}
      </select><small>已生效：{config.effective?.[k]?.model || localLabels[k]}{config.effective?.[k]?.url && <><br />{config.effective[k].url}</>}</small></label>)}</div>
      <p className="fineprint">一键创作会实际使用已保存的调用设置。白底图、透明贴片与样机保留本地制作；云端失败时提示重试。配置模型不代表已完成连接验证。</p>
      <details><summary>备用模型</summary>
        {kinds.map(([k,label])=><label key={k} className="field">{label}备用连接
          <select value={backups[k]||""} disabled={!selection[k] || selection[k]==="local-rules"} onChange={e=>setBackups({...backups,[k]:e.target.value})}>
            <option value="">无备用连接</option>
            {platforms.filter(p=>p.id!==selection[k] && p.connections[k]?.model && p.connections[k].selectable && (!config.formal||p.connections[k].approved))
              .map(p=><option key={p.id} value={p.id}>{p.label} · {p.connections[k].model}</option>)}
          </select></label>)}
      </details>
      {kinds.some(([k])=>!routes[k]&&config.defaults?.[k]?.model)&&<p className="fineprint">「已有配置」沿用之前保存或部署注入的连接。可在模型连接中保存并启用新的模型。</p>}
      <button className="primary" disabled={busy}>保存调用设置</button>
    </form>
  );
}

export default function ModelPlatforms({config,usage,costs,busy,act}) {
  const {platforms,routes} = config;
  const [category, chooseCategory] = useState("text");
  const [imageKind, chooseImageKind] = useState("image");
  const kind = category === "image" ? imageKind : category;
  const [ids, chooseId] = useState({});
  const [drafts, setDrafts] = useState([]);
  const available = [...platforms, ...drafts.filter(draft => !platforms.some(p => p.id === draft.id))]
    .filter(platform => platform.supported.includes(kind));
  const selected = available.find(p => p.id === ids[kind])
    || available.find(p => p.id === routes[kind])
    || available.find(p => p.connections[kind]?.model)
    || available.find(p => p.id === "custom") || available[0];

  function addPlatform() {
    const id = "custom-" + crypto.randomUUID().replaceAll("-", "");
    const platform = {id, label: "新平台", supported: kinds.map(([key]) => key),
      connections: Object.fromEntries(kinds.map(([key]) => [key, {}]))};
    setDrafts([...drafts, platform]);
    chooseId({...ids, [kind]: id});
  }
  return <>
    <div className="adminnav" aria-label="模型分类">
      {categories.map(([id, label]) => <button key={id} type="button" className={category === id ? "sel" : ""}
        aria-pressed={category === id} onClick={() => chooseCategory(id)}>{label}</button>)}
    </div>
    {category === "image" && <div className="adminnav" aria-label="图片用途">
      {[["image", "图片生成"], ["edit", "图片编辑"]].map(([id, label]) => <button key={id} type="button"
        className={imageKind === id ? "sel" : ""} onClick={() => chooseImageKind(id)}>{label}</button>)}
    </div>}
    <section className="formpanel">
      <h2>{categories.find(([id]) => id === category)[1]}平台</h2>
      <p>当前使用 {platforms.find(p => p.id === routes[kind])?.label || "默认连接"}
        {" · "}{config.effective?.[kind]?.model || localLabels[kind]}</p>
      <label className="field">选择平台<select aria-label="选择平台" value={selected.id}
        onChange={e => chooseId({...ids, [kind]: e.target.value})}>
        {available.map(platform => <option key={platform.id} value={platform.id}>
          {platform.label}{platform.connections[kind]?.model ? " · " + platform.connections[kind].model : ""}
        </option>)}
      </select></label>
      <button type="button" className="secondary" disabled={busy} onClick={addPlatform}>添加平台</button>
    </section>
    <Connection key={selected.id + kind} kind={kind} platform={selected} busy={busy} act={act}
      routeVersion={config.routeVersion} formal={config.formal} />
    <details className="formpanel"><summary>高级设置与用量</summary>
    <Routing key={config.routeVersion} config={config} act={act} busy={busy} />
    {costs && <ProviderCosts costs={costs} act={act} busy={busy} />}
    <h2>今日模型调用</h2><small>UTC · 未配置的能力使用本地处理</small>
    {!usage.length&&<p className="muted">今天还没有模型请求记录。</p>}
    {usage.map(row=><div className="reviewrow" key={[row.platform,row.model,row.kind].join("/")}><strong>{platforms.find(p=>p.id===row.platform)?.label||"默认连接"} · {row.model}</strong><p>{kinds.find(k=>k[0]===row.kind)?.[1]||row.kind} · 请求 {row.calls} 次 · 成功 {row.succeeded} 次 · 平均 {(row.meanMs/1000).toFixed(1)} 秒</p><small>输入 token：{row.inputTokens??"未返回"}；输出 token：{row.outputTokens??"未返回"}</small></div>)}
    </details>
  </>;
}
