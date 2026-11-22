import React, { useEffect, useRef, useState } from "react";
import { api, Field } from "./ui.jsx";

const kinds = [["text", "策划与文案"], ["image", "图片生成"], ["video", "视频生成"], ["vision", "商品与成品视觉审核"]];
const descriptions = {text: "写标题、卖点和短片脚本，只需要文本模型。", image: "生成图片环境，商品原图与准确文案在本地合成。", video: "生成动态环境，再合成商品原图、三镜字幕和配乐。", vision: "接收图片，检查商品与成品；不是图片生成模型。"};
const protocols = {chat: "Chat Completions", images: "Images Generations（同步图片）", "ark-video": "方舟视频任务（异步）"};
const localLabels = {text:"本地文案规则",image:"本地商品排版",video:"本地镜头运动",vision:"本地像素与文字检查"};

function Connection({ kind, platform, busy, act }) {
  const configured = platform.connections[kind];
  const [form, set] = useState({id:platform.id,label:platform.label,capability:kind,...configured,key:""});
  const [catalog,setCatalog] = useState(configured.catalog || null);
  const [syncing,setSyncing] = useState(false);
  const [err,setError] = useState("");
  const [probe,setProbe] = useState(null);
  const [probeBusy,setProbeBusy] = useState(false);
  const [pollAttempt,setPollAttempt] = useState(0);
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
  const catalogKey = JSON.stringify([form.url,form.modelsUrl,form.key,form.clearKey]);
  const synced = useRef(catalogKey);
  const visibleCatalog = synced.current===catalogKey ? catalog : null;
  async function sync() {
    setSyncing(true);setError("");
    try {setCatalog(await api("/admin/sync-models","POST",form));synced.current=catalogKey;}
    catch(e) {setError(e.message);}
    finally {setSyncing(false);}
  }
  async function test() {
    const retry=probe?.id&&probe.state!=="complete"&&tested.current===fingerprint;
    setProbeBusy(true);setError("");tested.current=fingerprint;
    try {setProbe(await api(retry ? "/admin/probes/"+probe.id+"/retry" : "/admin/probes","POST",form));setPollAttempt(n=>n+1);}
    catch(e) {setError(e.message);setProbeBusy(false);}
  }
  return <form className="formpanel integration" onSubmit={async e => {e.preventDefault(); if (await act("model-platform",form)) set({...form,key:"",clearKey:false});}}>
    <h3>{platform.label} · {kinds.find(k => k[0] === kind)[1]}</h3>
    {platform.id.startsWith("custom-") && <Field label="连接名称" name="label" form={form} set={set} required limit={60} />}
    <label className="field">接口协议<select value={form.protocol} onChange={e => set({...form,protocol:e.target.value})}><option value={form.protocol}>{protocols[form.protocol]}</option></select></label>
    <Field label="此能力的完整 API 地址" name="url" form={form} set={set} required limit={1200} placeholder={kind === "video" ? "https://…/contents/generations/tasks" : kind === "image" ? "https://…/images/generations" : "https://…/chat/completions"} />
    <details className="original"><summary>模型列表接口（可选）</summary><Field label="Models API 完整地址" name="modelsUrl" form={form} set={set} limit={1200} placeholder="留空按当前平台地址推导，必须与调用地址同源" /></details>
    <div className="model-tests"><button type="button" className="secondary" disabled={busy||syncing||probeBusy||!form.url} onClick={sync}>{syncing?"正在同步…":"同步最新模型"}</button><small>{visibleCatalog ? "上次同步："+new Date(catalog.updated).toLocaleString() : "尚未同步该连接的模型目录"}</small></div>
    {visibleCatalog && <label className="field">从平台最新目录选择<select aria-label="同步模型列表" value="" onChange={e=>set({...form,model:e.target.value})}><option value="">{catalog.models.length?"选择模型（不会自动替换当前模型）":"此接口未返回可用模型"}</option>{catalog.models.filter(m=>!m.known||m.kinds.includes(kind)).map(m=><option key={m.id} value={m.id}>{m.id}{!m.known?" · 能力未标注，请测试确认":""}</option>)}</select><small>已知不支持此能力的模型已过滤。模型可见不代表已开通调用权限。</small></label>}
    <Field label="此能力的模型 ID" name="model" form={form} set={set} required limit={180} placeholder={kind === "vision" ? "需要明确支持图片输入的模型" : "填写已开通的模型或接入点 ID"} />
    <label className="field">此能力的 API 密钥<input type="password" autoComplete="new-password" maxLength={2400} value={form.key} placeholder={configured.hasKey ? "已保存；地址不变时留空保留" : "填写密钥；本机服务可留空"} onChange={e=>set({...form,key:e.target.value})} /></label>
    {configured.hasKey && <label className="checkline"><input type="checkbox" checked={!!form.clearKey} onChange={e=>set({...form,clearKey:e.target.checked})} />清除此能力已保存的密钥</label>}
    <p className="fineprint">这里只保存这项能力，不改变其他能力的地址、模型或密钥。保存后还需在上方选为调用连接。</p>
    <div className="model-tests"><button className="primary" disabled={busy||probeBusy||syncing}>保存此能力连接</button><button type="button" className="secondary" disabled={busy||probeBusy||syncing||!form.url||!form.model} onClick={test}>{probeBusy?"正在测试…":kind==="image"?"测试连接 · 生成测试图":kind==="video"?"测试连接 · 生成测试视频":"测试连接"}</button></div>
    <p className="fineprint">测试使用当前表单的连接，不切换正式调用设置。图片和视频测试会真实生成测试素材，按供应商规则计费。</p>
    {err&&<p className="error" role="alert">{err}</p>}
    {probe && tested.current===fingerprint && <div className="connection-result" role="status"><strong>{probe.state==="complete"?"连接测试通过":probe.state==="failed"?"连接测试失败":"正在等待平台返回"}</strong><p>{probe.model} · {probe.message||probe.error||"测试在后台执行，完成后将在此显示结果。"}{probe.ms!=null&&" · "+(probe.ms/1000).toFixed(1)+" 秒"}</p>{probe.preview&&(kind==="video"?<video src={probe.preview} controls style={{maxWidth:"100%",maxHeight:360}} />:<img src={probe.preview} alt="接口实际返回的测试图" style={{maxWidth:"100%",maxHeight:360}} />)}</div>}
  </form>;
}

export default function ModelPlatforms({config,usage,busy,act}) {
  const {platforms,routes} = config;
  const [selection,select] = useState(Object.fromEntries(kinds.map(([k])=>[k,routes[k]||""])));
  const [kind,chooseKind] = useState("text");
  const [ids,chooseId] = useState({});
  const [draft,setDraft] = useState(null);
  const available = [...platforms,...(draft&&!platforms.some(p=>p.id===draft.id)?[draft]:[])].filter(p=>p.supported.includes(kind));
  const selected = available.find(p=>p.id===ids[kind])||available.find(p=>p.id===routes[kind])||available[0];
  return <>
    <form className="formpanel integration" onSubmit={e=>{e.preventDefault();act("model-routes",selection);}}>
      <h2>按能力选择调用平台</h2>
      <p>所有创作模型统一在这里配置。四项能力可以来自不同平台，各自使用独立的 API 地址、模型和密钥。</p>
      <div className="capability-grid">{kinds.map(([k,label])=><label className="field capability-card" key={k}><strong>{label}</strong><small>{descriptions[k]}</small><select aria-label={label+"调用连接"} value={selection[k]} onChange={e=>select({...selection,[k]:e.target.value})}>
        <option value="">{config.defaults?.[k]?.model ? "已有配置 · "+config.defaults[k].model : localLabels[k]+"（默认）"}</option>
        {(config.defaults?.[k]?.model || selection[k]==="local-rules") && <option value="local-rules">{localLabels[k]}</option>}
        {platforms.filter(p=>p.supported.includes(k)&&p.connections[k]?.model).map(p=><option value={p.id} key={p.id}>{p.label} · {p.connections[k].model}</option>)}
      </select><small>已生效：{config.effective?.[k]?.model || localLabels[k]}{config.effective?.[k]?.url && <><br />{config.effective[k].url}</>}</small></label>)}</div>
      <p className="fineprint">一键创作会实际使用已保存的调用设置。白底图、透明贴片与样机保留本地制作；云端失败时提示重试。配置模型不代表已完成连接验证。</p>
      {kinds.some(([k])=>!routes[k]&&config.defaults?.[k]?.model)&&<p className="fineprint">「已有配置」沿用之前保存或部署注入的连接。要调整它，请在下方保存独立连接，再在上方选用。</p>}
      <button className="primary" disabled={busy}>保存调用设置</button>
      <div className="model-tests"><button type="button" className="secondary" disabled={busy} onClick={()=>act("test-model",{})}>验证已保存的文案连接</button><button type="button" className="secondary" disabled={busy} onClick={()=>act("test-vision",{})}>验证已保存的视觉连接</button></div>
    </form>
    <h2>配置独立连接</h2>
    <p className="fineprint">选择能力与平台 → 填写连接并同步模型 → 测试并保存 → 在上方选用并保存调用设置。</p>
    <div className="adminnav">{kinds.map(([k,label])=><button key={k} className={k===kind?"sel":""} onClick={()=>chooseKind(k)}>{label}</button>)}</div>
    <label className="field">{kinds.find(k=>k[0]===kind)[1]}平台<select aria-label="配置平台" value={selected.id} onChange={e=>chooseId({...ids,[kind]:e.target.value})}>{available.map(p=><option key={p.id} value={p.id}>{p.label}</option>)}</select></label>
    {kind!=="text"&&<p className="fineprint">仅列出 Trupic 当前已接入此能力的连接类型。DeepSeek 的文案连接不用于生图、视频或图片审核。</p>}
    {kind==="video"&&<p className="fineprint">目前云端视频支持方舟异步任务协议；其他协议需要对应适配器，不能直接填入文案接口。</p>}
    <button type="button" className="secondary" disabled={busy} onClick={()=>{const p={id:"custom-"+crypto.randomUUID().replaceAll("-",""),label:"新增兼容连接",supported:[kind],connections:{[kind]:{url:"",model:"",hasKey:false,protocol:kind==="video"?"ark-video":kind==="image"?"images":"chat"}}};setDraft(p);chooseId({...ids,[kind]:p.id});}}>新增兼容连接</button>
    <Connection key={selected.id+kind} kind={kind} platform={selected} busy={busy} act={act} />
    <h2>今日模型调用</h2><small>UTC · 未配置的能力使用本地处理</small>
    {!usage.length&&<p className="muted">今天还没有模型请求记录。</p>}
    {usage.map(row=><div className="reviewrow" key={[row.platform,row.model,row.kind].join("/")}><strong>{platforms.find(p=>p.id===row.platform)?.label||"默认连接"} · {row.model}</strong><p>{kinds.find(k=>k[0]===row.kind)?.[1]||row.kind} · 请求 {row.calls} 次 · 成功 {row.succeeded} 次 · 平均 {(row.meanMs/1000).toFixed(1)} 秒</p><small>输入 token：{row.inputTokens??"未返回"}；输出 token：{row.outputTokens??"未返回"}</small></div>)}
  </>;
}
