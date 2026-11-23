// Run with node --test tests/miniprogram.cjs after npm run setup.
// Native wx network/storage calls are adapted to Node. All API traffic hits real Flask.
const { test } = require("node:test");
const assert = require("node:assert/strict");
const { readFileSync, mkdtempSync, rmSync } = require("node:fs");
const { tmpdir } = require("node:os");
const { resolve, join, dirname } = require("node:path");
const { spawn, execFileSync } = require("node:child_process");
const { once } = require("node:events");
const { createServer } = require("node:net");
const { setTimeout: delay } = require("node:timers/promises");
const vm = require("node:vm");

test(
  "朋友圈拍照直出、成品后选稿与换版，以及原有创作和导出",
  { timeout: 180000 },
  async (t) => {
    const root = resolve(__dirname, "..");
    const temp = mkdtempSync(join(tmpdir(), "trupic-wx-"));
    const listener = createServer().listen(0, "127.0.0.1");
    await once(listener, "listening");
    const port = listener.address().port;
    await new Promise((done) => listener.close(done));
    const origin = "http://127.0.0.1:" + port;
    const writer = require("node:http").createServer(async (req, res) => {
      let raw = "";
      for await (const chunk of req) raw += chunk;
      const { messages } = JSON.parse(raw);
      const input = JSON.parse(messages[1].content);
      const draft = { title: "今天这一杯，留给你", body: "看看杯中的颜色。", cta: "来看看。" };
      let result = {};
      if (input["候选"]) result = { approved: [0, 1, 2] };
      else if ("优惠" in input) result = {
        options: ["今天这一杯，留给你", "慢慢喝，也一起慢慢聊", "杯边藏着一圈春天的绿"].map(title =>
          ({ ...draft, title, shareTo: "午休常一起喝茶的同事", reply: "帮我留个座。" })),
      };
      else if ("writingBrief" in input) result = draft;
      else if (input.draft) result = { ok: true, headlineOk: true, closingOk: true };
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify({ choices: [{ message: { content: JSON.stringify(result) } }] }));
    }).listen(0, "127.0.0.1");
    await once(writer, "listening");
    t.after(() => writer.close());
    const server = spawn(join(root, ".venv/bin/python"), ["-m", "server.app"], {
      cwd: root,
      env: { ...process.env, PORT: String(port), TRUPIC_DATA: temp,
        TRUPIC_MODEL: "fixture-writer", TRUPIC_MODEL_URL: "http://127.0.0.1:" + writer.address().port + "/v1/chat/completions" },
      stdio: "ignore",
    });
    t.after(async () => {
      if (server.exitCode === null && !server.signalCode) {
        const closed = once(server, "exit");
        server.kill();
        await closed;
      }
      rmSync(temp, { recursive: true, force: true });
    });
    let up = false;
    for (let i = 0; i < 80 && !up; i++) {
      try {
        up = (await fetch(origin + "/api/state")).ok;
      } catch {
        await delay(100);
      }
    }
    assert.ok(up, "service started");
    const storage = new Map(),
      app = { globalData: {} },
      downloads = [],
      errors = [],
      confirmations = [];
    let confirmChange = true;
    let route = "",
      pageDefinition,
      album,
      clipboard;
    function transport(type) {
      return async (options) => {
        try {
          const headers = { ...options.header };
          let body;
          if (type === "upload") {
            body = new FormData();
            for (const [key, value] of Object.entries(options.formData || {})) body.append(key, value);
            body.append(
              "image",
              new Blob([readFileSync(options.filePath)], {
                type: "image/jpeg",
              }),
              "sample.jpg",
            );
          } else if (options.data) {
            headers["Content-Type"] = "application/json";
            body = JSON.stringify(options.data);
          }
          const res = await fetch(options.url, {
            method: type === "upload" ? "POST" : options.method || "GET",
            headers,
            body,
          });
          const response = {
            statusCode: res.status,
            header: Object.fromEntries(res.headers),
          };
          if (type === "file") {
            const path = join(temp, "file-" + downloads.length);
            require("node:fs").writeFileSync(
              path,
              Buffer.from(await res.arrayBuffer()),
            );
            downloads.push(path);
            response.tempFilePath = path;
          } else
            response.data =
              type === "upload" ? await res.text() : await res.json();
          options.success(response);
        } catch (e) {
          options.fail(e);
        }
      };
    }
    const wx = {
      request: transport("request"),
      uploadFile: transport("upload"),
      downloadFile: transport("file"),
      getAccountInfoSync: () => ({ miniProgram: { envVersion: "develop" } }),
      getStorageSync: (k) => storage.get(k),
      setStorageSync: (k, v) => storage.set(k, structuredClone(v)),
      switchTab: (o) => (route = o.url),
      navigateTo: (o) => (route = o.url),
      redirectTo: (o) => (route = o.url),
      showToast: () => {},
      showModal(o) {
        if (!o.success) return errors.push(o.content);
        confirmations.push(o.title);
        o.success({ confirm: confirmChange, cancel: !confirmChange });
      },
      pageScrollTo: () => {},
      setClipboardData: (o) => (clipboard = o.data),
      saveVideoToPhotosAlbum: (o) => {
        album = o.filePath;
        o.success();
      },
      saveImageToPhotosAlbum: (o) => {
        album = o.filePath;
        o.success();
      },
      chooseMedia: (o) =>
        o.success({
          tempFiles: [
            { tempFilePath: join(root, "miniprogram/images/tea.jpg") },
          ],
        }),
    };
    const modules = new Map();
    function load(file) {
      if (modules.has(file)) return modules.get(file);
      const module = { exports: {} };
      if (file.endsWith("/config.js"))
        return { development: origin, production: "" };
      const sandbox = {
        module,
        wx,
        require: (id) => load(resolve(dirname(file), id + ".js")),
        getApp: () => app,
        Page: (def) => (pageDefinition = def),
        setTimeout,
        clearTimeout,
        console,
      };
      vm.runInNewContext(readFileSync(file, "utf8"), sandbox, {
        filename: file,
      });
      modules.set(file, module.exports);
      return module.exports;
    }
    function page(name) {
      const file = join(root, "miniprogram/pages", name, name + ".js");
      modules.delete(file);
      load(file);
      return {
        ...pageDefinition,
        data: structuredClone(pageDefinition.data),
        setData(data) {
          Object.assign(this.data, data);
        },
      };
    }
    const click = (data) => ({ currentTarget: { dataset: data } });
    const input = (value) => ({ detail: { value } });
    const api = load(join(root, "miniprogram/lib/api.js"));
    const growth = page("promotion");
    growth.onLoad({});
    await growth.onShow();
    growth.setData({login:"wechat-owner",password:"wechat-fixture"});
    await growth.bind();
    assert.equal(growth.data.registered,true);
    const shared = growth.onShareAppMessage({target:{dataset:{query:growth.data.links[0].query}}});
    const invite = new URL("https://fixture.invalid"+shared.path).searchParams.get("invite");
    assert.ok(invite);
    await api.request("account/logout","POST",{});
    const joined = page("promotion");
    joined.onLoad({invite});
    joined.setData({login:"wechat-guest",password:"wechat-fixture"});
    await joined.bind();
    assert.equal(joined.data.registered,true);
    assert.equal(joined.data.error,"");
    await api.request("account/login","POST",{login:"wechat-owner",password:"wechat-fixture"});
    await growth.load();
    assert.equal(growth.data.invites[0].login,"wechat-guest");
    const home = page("home");
    home.onLoad();
    await home.toggleStudio();
    await home.preview();
    assert.ok(home.data.focusBrief);
    assert.match(home.data.briefError, /至少/);
    home.input(input("保留我的原创需求"));
    assert.equal(home.data.briefError, "");
    const gallery = page("inspiration");
    gallery.filter(click({ cat: "茶饮" }));
    assert.equal(gallery.data.samples.length, 1);
    gallery.open(click({ id: "tea" }));
    confirmChange = false;
    gallery.use();
    assert.equal(gallery.data.selected.id, "tea");
    assert.equal(storage.get("trupic.draft").brief, "保留我的原创需求");
    assert.equal(route, "");
    assert.equal(app.globalData.sample, undefined);
    confirmChange = true;
    gallery.use();
    await home.onShow();
    assert.equal(home.data.topics.length, 2);
    assert.equal(route, "/pages/home/home");
    assert.match(home.data.brief, /抹茶/);
    home.addPhoto();
    for (let i = 0; i < 100 && !home.data.assetImage; i++) await delay(50);
    assert.ok(home.data.assetImage);
    const originalDownload = api.download;
    api.download = async () => { throw new Error("图片连接中断"); };
    await home.showPhoto();
    assert.equal(home.data.assetImage, "");
    assert.equal(home.data.photoError, "图片连接中断");
    api.download = originalDownload;
    await home.showPhoto();
    assert.equal(home.data.photoError, "");
    assert.ok(home.data.assetImage);
    await home.startMark();
    home.createSelectorQuery = () => ({
      select() {
        return this;
      },
      boundingClientRect(cb) {
        cb({ left: 0, top: 0, width: 400, height: 600 });
        return this;
      },
      exec() {},
    });
    home.markPoint({ changedTouches: [{ clientX: 100, clientY: 120 }] });
    home.markPoint({ changedTouches: [{ clientX: 300, clientY: 480 }] });
    assert.deepEqual(
      Array.from(home.data.identityRegion),
      [0.25, 0.2, 0.75, 0.8],
    );
    home.acceptPhoto();
    assert.equal(home.data.assetConfirmed, true);
    for (const kind of ["poster", "video", "copy"]) {
      home.changeKind(click({ kind }));
      if (kind === "poster") {
        home.selectFormat({ ...click({ key: "ratio" }), ...input(1) });
        home.selectFormat({ ...click({ key: "dpi" }), ...input(1) });
      }
      if (kind === "video") {
        await home.showPhoto();
        await home.startMark(click({ target: "detail" }));
        home.markPoint({ changedTouches: [{ clientX: 240, clientY: 300 }] });
        home.markPoint({ changedTouches: [{ clientX: 312, clientY: 390 }] });
        home.detailLabel(input("杯壁上的茶奶纹路"));
        home.acceptPhoto();
        assert.deepEqual(Array.from(home.data.identityRegion), [0.25, 0.2, 0.75, 0.8]);
        home.selectFormat({ ...click({ key: "ratio" }), ...input(4) });
        home.selectFormat({ ...click({ key: "resolution" }), ...input(0) });
      }
      await home.preview();
      assert.equal(route, "/pages/confirm/confirm");
      const confirm = page("confirm");
      confirm.onLoad();
      const p = confirm.data.preview;
      assert.equal(p.kind, kind);
      if (kind === "video") assert.equal(p.plan.markedDetail.label, "杯壁上的茶奶纹路");
      assert.equal(
        p.plan.design?.id,
        kind === "copy" ? undefined : gallery.data.samples[0].style,
      );
      if (p.requiresCopyChoice) {
        await confirm.submit();
        assert.equal(route, "/pages/confirm/confirm");
        await confirm.loadOptions();
        assert.ok(confirm.data.options.length >= 2, confirm.data.error);
        confirm.chooseCopy(input(confirm.data.options[1].token));
      }
      await confirm.submit();
      assert.ok(
        route.startsWith("/pages/result/result?job="),
        confirm.data.error,
      );
      const job = route.split("=").pop();
      await confirm.submit();
      assert.equal(route.split("=").pop(), job);
      const result = page("result");
      result.onLoad({ job });
      for (let i = 0; i < 1200; i++) {
        await result.refresh();
        result.stop();
        if (result.data.state === "complete") break;
        assert.notEqual(result.data.state, "failed", result.data.error);
        await delay(60);
      }
      assert.equal(result.data.state, "complete", result.data.error);
      assert.ok(result.data.version.title);
      if (kind === "copy") {
        result.copy();
        assert.ok(clipboard.includes(result.data.version.title));
      } else {
        await result.save();
        assert.ok(album);
        if (kind === "poster") {
          const bytes = readFileSync(album);
          assert.equal(bytes.readUInt32BE(16), 1080);
          assert.equal(bytes.readUInt32BE(20), 1080);
          assert.equal(p.plan.output.dpi, 150);
        } else {
          const probe = execFileSync(
            "ffprobe",
            [
              "-v",
              "error",
              "-select_streams",
              "v:0",
              "-show_entries",
              "stream=width,height",
              "-of",
              "csv=p=0",
              album,
            ],
            { encoding: "utf8" },
          );
          assert.equal(probe.trim(), "1280,720");
        }
      }
      if (kind === "poster") {
        const first = result.data.version;
        const originalImage = readFileSync(result.data.media);
        await result.revise(click({ action: "layout" }));
        while (result.job) {
          result.stop();
          assert.notEqual(result.data.state, "failed", result.data.error);
          await delay(80);
          await result.refresh();
        }
        assert.equal(result.data.version.n, 2);
        assert.equal(
          result.data.version.plan.design.id,
          first.layoutSuggestion.id,
        );
        assert.equal(result.data.version.body, first.body);
        assert.equal(
          originalImage.equals(readFileSync(result.data.media)),
          false,
        );
        await result.selectVersion(input(1));
        assert.equal(result.data.version.n, 1);
        await result.restore();
        assert.equal(result.data.work.current, 1);
        assert.equal(result.data.work.versions.length, 2);
      }
      if (kind === "video") {
        confirmChange = false;
        const existing = home.data.brief;
        home.useTopic(click({ id: home.data.topics[0].topicId }));
        assert.equal(home.data.brief, existing);
        confirmChange = true;
        home.useTopic(click({ id: home.data.topics[0].topicId }));
        assert.equal(home.data.brief, home.data.topics[0].brief);
      }
    }
    const mine = page("mine");
    await mine.load();
    mine.edit();
    mine.setData({ form: { ...mine.data.form, name: "修改中的店名" } });
    confirmChange = false;
    mine.close();
    assert.equal(mine.data.edit, true);
    assert.equal(mine.data.form.name, "修改中的店名");
    confirmChange = true;
    mine.close();
    assert.equal(mine.data.edit, false);
    assert.match(confirmations.at(-1), /未保存/);
    assert.equal(mine.data.works.length, 3);
    assert.equal(mine.data.credits, 103);
    const state = await api.request("state");
    assert.equal(state.assets.length, 1);
    assert.ok(state.recs.find((r) => r.topicId === home.data.topicId).adopted);
    const reopened = page("home");
    reopened.onLoad();
    reopened.changeKind(click({ kind: "poster" }));
    assert.equal(reopened.data.format.ratio, "1:1");
    async function waitForMoment(result) {
      for (let i = 0; i < 1200; i++) {
        await result.refresh();
        result.stop();
        assert.notEqual(result.data.state, "failed", result.data.error);
        assert.notEqual(result.data.state, "error", result.data.error);
        if (result.data.state === "complete" && result.data.media) return;
        await delay(60);
      }
      assert.fail("朋友圈没有交付");
    }
    await reopened.onShow();
    assert.equal(reopened.data.studio, false);
    assert.equal(reopened.data.momentRatio, "portrait");
    assert.equal(reopened.data.momentCost, state.prices.poster);
    await reopened.makeMoment();
    assert.equal(reopened.data.momentJob, "");
    reopened.takeMomentPhoto();
    for (let i = 0; i < 300 && reopened.data.busy; i++) await delay(60);
    assert.ok(reopened.data.momentAsset, reopened.data.momentError);
    await assert.rejects(api.request("moments", "POST", {
      asset: reopened.data.momentAsset.id, confirmed: true, confirmedCost: state.prices.poster + 1, requestKey: "stale-price",
    }), /用量已更新/);
    const note = "今天多做了 10 杯抹茶，下午 4 点能取。";
    for (const message of ["", note]) {
      if (message) {
        reopened.momentFormat(click({ ratio: "story" }));
        assert.equal(reopened.data.momentJob, "");
        reopened.momentInput(input(message));
        const request = api.request;
        api.request = async (path, ...args) => {
          const response = await request(path, ...args);
          if (path === "moments") throw new Error("提交后连接中断");
          return response;
        };
        try {
          await reopened.makeMoment();
          assert.equal(reopened.data.momentError, "提交后连接中断");
          assert.equal(reopened.data.momentJob, "");
        } finally {
          api.request = request;
        }
      }
      await Promise.all([reopened.makeMoment(), reopened.makeMoment()]);
      const job = reopened.data.momentJob;
      assert.ok(job, reopened.data.momentError);
      assert.equal(route, "/pages/result/result?job=" + job);
      const result = page("result");
      result.onLoad({ job });
      await waitForMoment(result);
      assert.equal(result.data.isMoment, true);
      assert.equal(result.data.version.asset, reopened.data.momentAsset.id);
      result.copy();
      assert.ok(clipboard.trim());
      if (message) assert.ok(clipboard.includes(message));
      else assert.doesNotMatch(clipboard, /元|折|限量|促销|分享今天的店里实拍/);
      await result.save();
      const picture = readFileSync(album);
      assert.equal(picture.readUInt32BE(16), 1080);
      assert.equal(picture.readUInt32BE(20), message ? 1920 : 1440);
      assert.equal(result.data.version.plan.moment.workflowVersion, 2);
      assert.ok(result.data.version.writingSkill);
      assert.ok(result.data.version.plan.skillPlan.skills.some(skill => skill.id === "poster_design"));
      const resumed = page("home");
      resumed.onLoad();
      await resumed.onShow();
      await resumed.makeMoment();
      assert.equal(resumed.data.momentJob, job);
      assert.equal(resumed.data.momentRatio, message ? "story" : "portrait");
      if (message) {
        await result.openCopies();
        assert.ok(result.data.copyMenu.options.length >= 2);
        const option = result.data.copyMenu.options.length - 1;
        const selected = result.data.copyMenu.options[option];
        await result.revise(click({ action: "moment-copy", option }));
        await waitForMoment(result);
        assert.equal(result.data.version.n, 2);
        assert.equal(result.data.version.body, selected.body);
        result.copy();
        const chosenCopy = clipboard;
        const beforeLayout = readFileSync(result.data.media);
        await result.revise(click({ action: "layout" }));
        await waitForMoment(result);
        assert.equal(result.data.version.n, 3);
        assert.equal(beforeLayout.equals(readFileSync(result.data.media)), false);
        result.copy();
        assert.equal(clipboard, chosenCopy);
        await result.save();
        await result.selectVersion(input(2));
        await result.restore();
        assert.equal(result.data.work.current, 1);
      }
    }
    const afterMoments = await api.request("state");
    assert.equal(afterMoments.works.length, state.works.length + 2);
    assert.equal(state.credits - afterMoments.credits, 2 * state.prices.poster + 2 * state.prices.revision);
    assert.deepEqual(errors, []);
  },
);
