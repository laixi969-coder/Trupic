const api = require("../../lib/api");
const root = "agent/blind-reviews";
const groups = ["food", "retail", "service"];
const labels = ["餐饮", "零售", "到店服务"];
const preferences = { A:"作品 A", B:"作品 B", tie:"两版都可以", neither:"两版都退回" };

Page({
  data:{ busy:false,error:"",groups:labels,sector:0,groupBriefs:[],briefIndex:0,works:[],workIndex:-1,
    versions:[],versionIndex:0,bases:[],baseIndex:0,reviews:[],review:null,samples:[],preference:"",minutes:"",readyToSubmit:false },
  onLoad(query={}) {
    this.query=query;
    if(query.id) return this.openCase(query.id);
    return this.loadIndex();
  },
  onHide() { this.refreshOnReturn = !this.query.id; },
  onShow() {
    if (this.refreshOnReturn) {
      this.refreshOnReturn = false;
      return this.loadIndex();
    }
  },
  onUnload() { this.closed=true; },
  async run(fn) {
    if(this.data.busy) return;
    this.setData({busy:true,error:""});
    try { await fn(); } catch(e) { if (!this.closed) this.setData({error:e.message}); }
    finally { if(!this.closed) this.setData({busy:false}); }
  },
  async loadIndex() {
    await this.run(async()=>{
      const [catalog, candidates, index] = await Promise.all([api.request("agent/blind-briefs"),api.request("agent/blind-candidates"),api.request(root)]);
      if(this.closed) return;
      const priorWork=this.data.works[this.data.workIndex]?.work;
      const priorBrief=this.data.groupBriefs[this.data.briefIndex];
      const version=this.data.versions[this.data.versionIndex]?.n ?? Number(this.query.version);
      const base=this.data.bases[this.data.baseIndex]?.n;
      this.catalog=catalog.briefs;
      const at=candidates.candidates.findIndex(w=>w.work===(priorWork || this.query.work));
      this.setData({works:candidates.candidates,reviews:index.reviews,summary:index.summary});
      this.selectSector(priorBrief ? this.data.sector : 0, priorBrief?.id);
      this.selectWork(at, version, !priorBrief, base);
    });
  },
  selectSector(i, briefId) {
    const groupBriefs=this.catalog.filter(b=>b.sector===groups[i]);
    const briefIndex=Math.max(0,groupBriefs.findIndex(b=>b.id===briefId));
    this.setData({sector:i,briefIndex,groupBriefs});
  },
  groupChanged(e) { this.selectSector(Number(e.detail.value)); },
  briefChanged(e) { this.setData({briefIndex:Number(e.detail.value)}); },
  selectWork(i, requestedVersion, matchBrief=true, requestedBase) {
    const w=this.data.works[i];
    const versions=(w?.versions||[]).map(n=>({n,label:n===1?"只评首稿":"版本 "+n}));
    const at=versions.findIndex(v=>v.n===requestedVersion);
    this.setData({workIndex:i,versions});
    this.selectVersion(at<0?Math.max(0,versions.length-1):at, requestedBase);
    const linked=matchBrief && this.catalog.find(b=>b.id===w?.briefId);
    if(linked) this.selectSector(groups.indexOf(linked.sector), linked.id);
  },
  workChanged(e) { this.selectWork(Number(e.detail.value)); },
  selectVersion(versionIndex, requestedBase) {
    const versions=this.data.versions;
    const bases=versions.filter(v=>v.n<versions[versionIndex].n)
      .map(v=>({n:v.n,label:v.n===1?"版本 1（首稿）":v.label}));
    const at=bases.findIndex(v=>v.n===requestedBase);
    this.setData({versionIndex,bases,baseIndex:at<0?Math.max(0,bases.length-1):at});
  },
  versionChanged(e) { this.selectVersion(Number(e.detail.value)); },
  baseChanged(e) { this.setData({baseIndex:Number(e.detail.value)}); },
  useBrief() {
    const brief=this.data.groupBriefs[this.data.briefIndex];
    if (!brief) return;
    return this.run(async()=>{
      const {workspace}=await api.request("agent");
      if (this.closed) return;
      const shared=getApp().globalData;
      const entry={workspace,text:brief.creationDraft,blindBriefId:brief.id,send:false};
      shared.agentEntry=entry;
      wx.navigateTo({url:"/pages/agent/agent?mode=new",fail:()=>{
        if(shared.agentEntry===entry) shared.agentEntry=null;
        if(!this.closed) this.setData({error:"未能打开营销助理，请重试。"});
      }});
    });
  },
  start() {
    this.run(async()=>{
      const {works,workIndex,groupBriefs,briefIndex,versions,versionIndex,bases,baseIndex}=this.data;
      const row=await api.request(root,"POST",{work:works[workIndex].work,briefId:groupBriefs[briefIndex].id,
        baseVersion:bases[baseIndex]?.n || 1, revisionVersion:versions[versionIndex].n});
      if(!this.closed) wx.navigateTo({url:"/pages/blind/blind?id="+row.id});
    });
  },
  resume(e) { wx.navigateTo({url:"/pages/blind/blind?id="+e.currentTarget.dataset.id}); },
  openCase(id) {
    this.run(async()=>{
      const review=await api.request(root+"/"+id);
      const samples=await Promise.all(review.options.map(async o=>{
        const local=await api.download(o.url);
        const text=review.kind==="copy"?wx.getFileSystemManager().readFileSync(local,"utf8"):"";
        return {slot:o.slot,local,text,answer:"",reason:""};
      }));
      if(!this.closed) {
        this.setData({review,samples});
        if(review.reveal) this.showResult(review);
      }
    });
  },
  showResult(review) {
    const r=review.reveal;
    const shown=Object.entries(r.versions).map(([slot,v])=>({
      slot,role:v.role==="first"?"首稿":slot===r.baseSlot?"对照版":"修改稿",version:v.version,
      label:r.ratings[slot].publish?"可以直接发":"需要修改",reason:r.ratings[slot].reason,
      points:v.credits==null?"暂无流水":v.credits+" 积分",
      elapsed:v.requestToDeliverySeconds==null?"暂无计时":v.requestToDeliverySeconds+" 秒",
      rendering:v.productionSeconds==null?"暂无计时":v.productionSeconds+" 秒",visualEngine:v.visualEngine,
      charge:v.modelCharge ? v.modelCharge.amount+" "+v.modelCharge.currency : "",
    }));
    this.setData({review,shown,preferred:preferences[r.preference]||"",
      minutesLabel:r.merchantEditMinutes==null?"未填写":r.merchantEditMinutes+" 分钟"});
  },
  evaluate(samples, preference) {
    const complete=samples.every(s=>s.answer==="yes" || (s.answer==="no"&&s.reason.trim()));
    const picks=samples.filter(s=>s.answer==="yes").map(s=>({key:s.slot,label:preferences[s.slot]}));
    if(picks.length===samples.length) picks.push({key:"tie",label:preferences.tie});
    if(!picks.length) picks.push({key:"neither",label:preferences.neither});
    this.setData({samples,preference,picks,allRated:!!complete,readyToSubmit:!!complete && (samples.length===1 || !!preference)});
  },
  rate(e) {
    const d=e.currentTarget.dataset;
    this.evaluate(this.data.samples.map(s=>s.slot===d.slot?{...s,answer:d.answer}:s),"");
  },
  reason(e) {
    this.evaluate(this.data.samples.map(s=>s.slot===e.currentTarget.dataset.slot?{...s,reason:e.detail.value}:s),this.data.preference);
  },
  choose(e) { this.evaluate(this.data.samples,e.currentTarget.dataset.key); },
  minutesChanged(e) { this.setData({minutes:e.detail.value}); },
  played(e) { this.data.samples.forEach(s=>{if(s.slot!==e.currentTarget.dataset.slot)wx.createVideoContext("film"+s.slot,this).pause();}); },
  submit() {
    this.run(async()=>{
      const {samples,minutes,preference,review}=this.data;
      const time=minutes.trim()===""?null:Number(minutes);
      if(time!==null && (!Number.isFinite(time)||time<0)) throw new Error("请填写有效的改稿分钟数。");
      const ratings=Object.fromEntries(samples.map(s=>[s.slot,{publish:s.answer==="yes",reason:s.answer==="no"?s.reason.trim():""}]));
      const row=await api.request(root+"/"+review.id+"/answer","POST",{ratings,preference:samples.length>1?preference:null,merchantEditMinutes:time});
      if(!this.closed) this.showResult(row);
    });
  },
});
