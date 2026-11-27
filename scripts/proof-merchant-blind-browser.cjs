/* Record the live Trupic ballot, or bundle its same React component for a private offline trial. */
const fs = require("node:fs");
const { createHash } = require("node:crypto");
const path = require("node:path");
const { performance } = require("node:perf_hooks");
const esbuild = require("esbuild");
const puppeteer = require("puppeteer-core");
const root = path.resolve(__dirname, "..");
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));

async function launch(chrome) {
  return await puppeteer.launch({executablePath: chrome, headless: true,
    args: ["--no-first-run", "--disable-sync", "--disable-background-networking", "--autoplay-policy=no-user-gesture-required"]});
}

async function record(params) {
  const browser = await launch(params.chrome);
  let running = false;
  let captures;
  try {
    const page = await browser.newPage();
    await page.setViewport({width: 1280, height: 960, deviceScaleFactor: 1});
    await browser.setCookie({name:"trupic_workspace", value:params.cookie, domain:"127.0.0.1", path:"/"});
    await page.setRequestInterception(true);
    page.on("request", req => {
      if (req.url().startsWith(params.base + "/") || /^(blob|data):/.test(req.url())) req.continue();
      else req.abort();
    });
    const requests = [];
    page.on("response", res => {
      const pathname = new URL(res.url()).pathname;
      if (pathname.startsWith("/api/")) {
        requests.push({method:res.request().method(),status:res.status(),path:pathname.replace(params.caseId,"<review>")});
      }
    });
    await page.goto(params.base + "/#blind-review/" + params.caseId,{waitUntil:"networkidle2"});
    await page.waitForFunction(() => document.querySelectorAll("video").length === 2, {timeout:15000});
    const errors = [];
    page.on("pageerror", e => errors.push(e.message));
    const frames = [];
    const zero = performance.now();
    running = true;
    captures = (async () => {
      while(running) {
        const clock = (performance.now() - zero) / 1000;
        const current = await page.evaluate(() => Array.from(document.querySelectorAll("video")).map(v=>v.currentTime));
        const file = String(frames.length).padStart(5,"0") + ".jpg";
        await page.screenshot({path:path.join(params.temp,"frames",file), type:"jpeg", quality:88});
        frames.push({time:clock, file, play:{A:current[0] || 0, B: current[1] || 0}});
        await wait(58);
      }
    })();
    const textClick = async (context, text) => {
      const element = await context.evaluateHandle((node, wanted) =>
        Array.from(node.querySelectorAll('button,label,option,input[type=submit]')).find(el=>
          el.textContent.trim() === wanted || el.getAttribute('aria-label')===wanted), text);
      if (!(await element.asElement())) throw new Error("未找到盲评操作：" + text);
      await element.asElement().click();
      await element.dispose();
    };
    const body = await page.$("body");
    await wait(600);
    for(const [index,slot] of ["A","B"].entries()) {
      const videos=await page.$$("video");
      const player=videos[index];
      await player.evaluate(v=>v.scrollIntoView({block:"center"}));
      await player.evaluate(v=>{v.muted=false;return v.play()});
      await page.waitForFunction(n=>document.querySelectorAll("video")[n]?.ended,{timeout:23000},index);
      const card=await player.evaluateHandle(v=>{
        for(let el=v.parentElement;el;el=el.parentElement) {
          if(el.querySelectorAll("video").length===1 && /可以直接发/.test(el.textContent) && /需要修改/.test(el.textContent)) return el;
        }
        return null;
      });
      if(!(await card.asElement())) throw new Error("未找到样片 " + slot + " 对应的评价");
      const publish = slot === params.prefer;
      await textClick(card, publish ? "可以直接发" : "需要修改");
      if (!publish) {
        const field=await card.asElement().$("textarea,input[type=text]");
        if(!field) throw Error("缺少退稿原因输入");
        await field.click();
        await page.keyboard.sendCharacter(params.reason);
      }
      await wait(700);
    }
    await textClick(body,"作品 " + params.prefer);
    await wait(600);
    await textClick(body,"提交并揭晓");
    await page.waitForFunction(()=>document.body.innerText.includes("首稿") && !Array.from(document.querySelectorAll("button")).some(el=>el.textContent==="提交并揭晓"),{timeout:8000});
    await page.evaluate(()=>window.scrollTo(0,0));
    await wait(950);
    await page.evaluate(()=>window.scrollTo(0,document.body.scrollHeight));
    await wait(2100);
    running=false;
    await captures;
    if (errors.length || requests.some(r=>r.path==="/api/state" || r.path.startsWith("/api/works/")))
      throw new Error("提交前出现无关作品数据或前端错误 " + JSON.stringify({errors,requests}));
    return {frames, requests};
  } finally {
    running=false;
    if(captures) await captures.catch(()=>{});
    await browser.close();
  }
}

async function offline(cfg) {
  const data={brief:cfg.blank.brief,briefId:cfg.blank.briefId,source:"demo",factChanges:cfg.reveal.factChanges,firstDraftEvidence:cfg.reveal.firstDraftEvidence,
    samples:["A","B"].map(slot=>({version:cfg.reveal.versions[slot],media:fs.readFileSync(cfg.media[slot]).toString("base64")}))};
  const trialKey=createHash("sha256").update(JSON.stringify(data)).digest("hex");
  const code=`
    import React, {useState} from "react";
    import {createRoot} from "react-dom/client";
    import {ReviewBallot} from "./src/BlindReview.jsx";
    const data=JSON.parse(document.getElementById("packet").textContent);
    const key="trupic.matcha.blind.local.${trialKey}";
    const rand=()=>Boolean(crypto.getRandomValues(new Uint8Array(1))[0]&1);
    function load(){
      try {const s=JSON.parse(localStorage.getItem(key)); if(s && typeof s.flip==="boolean" && s.started>0) return s;} catch{}
      return {flip:rand(),started:Date.now(),answer:null};
    }
    function save(s){try{localStorage.setItem(key, JSON.stringify(s));}catch{}}
    function trial() {
      const [s,set]=useState(()=>{const initial=load();save(initial);return initial});
      const [urls]=useState(()=>data.samples.map(sample=>URL.createObjectURL(new Blob(
        [Uint8Array.from(atob(sample.media),c=>c.charCodeAt(0))],{type:"video/mp4"}))));
      const indices=s.flip?[1,0]:[0,1];
      const options=["A","B"].map((slot,i)=>({slot,url:urls[indices[i]]}));
      const versions=Object.fromEntries(options.map((item,i)=>[item.slot,data.samples[indices[i]].version]));
      const baseSlot=versions.A.version < versions.B.version ? "A" : "B";
      const firstDraftSlot=versions[baseSlot].version===1 ? baseSlot : null;
      const revisionSlot=baseSlot==="A"?"B":"A";
      const reveal=s.answer?{...s.answer,versions,baseSlot,firstDraftSlot,revisionSlot,factChanges:data.factChanges,firstDraftEvidence:data.firstDraftEvidence,
        firstDraftPublish:s.answer.ratings[firstDraftSlot]?.publish??null,firstDraftReason:s.answer.ratings[firstDraftSlot]?.reason??null}:null;
      const review={id:"local",briefId:data.briefId,brief:data.brief,source:"demo",kind:"video",options,status:reveal?"submitted":"open",reveal};
      const onAnswer=async values=>{
        const next={...s,answer:{...values,reviewSeconds:Math.round((Date.now()-s.started)/1000),merchantEditMinutes:values.merchantEditMinutes??null}};
        save(next);set(next);window.scrollTo(0,0);
      };
      return <main className="br-page"><div className="local-trial"><strong>抹茶盲选 · 本机试玩</strong>
        <span>独立播放两条 15 秒短片。此处的选择仅保存在当前浏览器，不计入商家统计。</span></div>
        <ReviewBallot key={s.started} review={review} onAnswer={onAnswer}/>
        {reveal&&<div className="local-trial"><button onClick={()=>{const next={flip:rand(),started:Date.now(),answer:null};save(next);set(next);window.scrollTo(0,0)}}>重新随机盲选</button></div>}</main>;
    }
    createRoot(document.getElementById('root')).render(React.createElement(trial));
  `;
  const bundle=await esbuild.build({stdin:{contents:code,loader:"jsx",resolveDir:root},
    bundle:true,minify:true,define:{"process.env.NODE_ENV":'"production"'},write:false,outfile:"local.js"});
  const script=bundle.outputFiles.find(r=>r.path.endsWith(".js")).text.replace(/<\/script/gi,"<\\/script");
  const css=bundle.outputFiles.find(r=>r.path.endsWith(".css"))?.text||"";
  const html='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>抹茶 · 商家盲选</title><style>'+
    'html{background:#f5f6f2;color:#22392e;font-family:system-ui,sans-serif}body{margin:0}*{box-sizing:border-box}button,input,textarea,select{font:inherit}.local-trial{display:flex;align-items:baseline;flex-wrap:wrap;gap:8px 18px;padding:14px 20px;margin:0 auto;max-width:1060px;background:#e7f2e9;border-radius:12px}.local-trial span{font-size:14px;color:#496353}.local-trial button{cursor:pointer}'+
    css+'</style><div id="root"></div><script type="application/json" id="packet">'+JSON.stringify(data).replace(/</g,"\\u003c")+'</script><script>'+script+'</script></html>';
  fs.writeFileSync(cfg.output,html);
  const browser=await launch(cfg.chrome);
  try{
    const page=await browser.newPage(); const calls=[];
    page.on("request",r=>{if(/^https?:/.test(r.url())) calls.push(r.url())});
    await page.goto(require("node:url").pathToFileURL(cfg.output).href);
    await page.waitForFunction(()=>document.querySelectorAll("video").length===2);
    const protectedWords=await page.evaluate(()=>/首稿用时|原版|版本 1|V1/.test(document.body.innerText));
    if(calls.length || protectedWords) throw Error("本机盲选初次加载泄露结果或请求网络");
    // Submit a disposable answer in a new browser profile; the packaged HTML stays blank.
    await page.$$eval(".br-sample", samples=>samples.forEach(card=>[...card.querySelectorAll("button")].find(b=>b.textContent==="可以直接发").click()));
    await page.waitForFunction(()=>[...document.querySelectorAll("button")].some(b=>b.textContent==="两版都可以"&&!b.disabled));
    await page.$$eval("button", buttons=>buttons.find(b=>b.textContent==="两版都可以").click());
    await page.waitForSelector("button[type=submit]:not(:disabled)");
    await page.click("button[type=submit]");
    await page.waitForSelector(".br-results");
    await page.reload();
    await page.waitForSelector(".br-results");
    await page.$$eval("button", buttons=>buttons.find(b=>b.textContent==="重新随机盲选").click());
    await page.waitForFunction(()=>!document.querySelector(".br-results") && document.querySelectorAll("video").length===2);
    if(calls.length) throw Error("本机回放出现网络请求");
    return {bytes:Buffer.byteLength(html),offlineRequests:0,reopenAndResetVerified:true};
  } finally {await browser.close();}
}

const options=JSON.parse(fs.readFileSync(0,"utf8"));
(process.argv[2]==="record"?record(options):offline(options)).then(out=>process.stdout.write(JSON.stringify(out))).catch(error=>{console.error(error.message);process.exitCode=1});
