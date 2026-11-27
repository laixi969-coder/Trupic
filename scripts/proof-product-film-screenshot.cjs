/* Capture the actual local merchant task card. The temporary cookie arrives via stdin. */
const puppeteer = require("puppeteer-core");
const fs = require("node:fs");

async function capture(params) {
  const browser = await puppeteer.launch({executablePath: params.chrome, headless: true,
    args: ["--disable-background-networking", "--disable-sync", "--no-first-run"]});
  try {
    const page = await browser.newPage();
    const before = params.output.endsWith("quote.png");
    await page.setViewport({width: 1320, height: before ? 1050 : 1440, deviceScaleFactor: 1});
    await page.setRequestInterception(true);
    page.on("request", request => {
      const url = request.url();
      if (url.startsWith(params.base + "/") || url.startsWith("data:") || url.startsWith("blob:")) {
        request.continue();
      } else {
        request.abort();
      }
    });
    await browser.setCookie({name: "trupic_workspace", value: params.cookie, domain: "127.0.0.1", path: "/"});
    await page.evaluateOnNewDocument((store, chat) => sessionStorage.setItem(store, chat),
      "trupic.agent." + params.workspace, params.chat);
    await page.goto(params.base, {waitUntil: "networkidle2"});
    const card = await page.waitForSelector(".agent-task.status-" + (before ? "quoted" : "delivered"), {visible: true});
    if (before) {
      await card.evaluate(node => {
        const field = Array.from(node.querySelectorAll("details")).find(detail => /分镜|口播/.test(detail.querySelector("summary")?.textContent || ""));
        if (field) field.open = true;
      });
    } else {
      await page.waitForSelector(".agent-output video");
      await page.evaluate(async () => {
        const video = document.querySelector(".agent-output video");
        if (video.readyState < 1) await new Promise(resolve => video.addEventListener("loadedmetadata", resolve, {once: true}));
        const seek = new Promise(resolve => video.addEventListener("seeked", resolve, {once: true}));
        video.currentTime = 4;
        await seek;
      });
    }
    await card.evaluate(node => node.scrollIntoView({block: "center"}));
    await page.screenshot({path: params.output});
    if (before) {
      const response = page.waitForResponse(r => r.request().method() === "POST" && r.url().endsWith("/approve"));
      await page.click(".agent-approve-btn");
      const completed = await response;
      if (!completed.ok()) throw new Error("页面确认失败 " + completed.status());
      process.stdout.write(JSON.stringify({
        approval: JSON.parse(completed.request().postData()), accepted: await completed.json()
      }));
    }
  } finally {
    await browser.close();
  }
}
capture(JSON.parse(fs.readFileSync(0, "utf8"))).catch(e => { console.error(e); process.exitCode = 1; });
