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
  "灵感回填、原图确认、方案计费、生成、导出及作品恢复",
  { timeout: 90000 },
  async (t) => {
    const root = resolve(__dirname, "..");
    const temp = mkdtempSync(join(tmpdir(), "trupic-wx-"));
    const listener = createServer().listen(0, "127.0.0.1");
    await once(listener, "listening");
    const port = listener.address().port;
    await new Promise((done) => listener.close(done));
    const origin = "http://127.0.0.1:" + port;
    const server = spawn(join(root, ".venv/bin/python"), ["-m", "server.app"], {
      cwd: root,
      env: { ...process.env, PORT: String(port), TRUPIC_DATA: temp },
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
      errors = [];
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
      showModal: (o) => errors.push(o.content),
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
    const home = page("home");
    home.onLoad();
    const gallery = page("inspiration");
    gallery.filter(click({ cat: "茶饮" }));
    assert.equal(gallery.data.samples.length, 1);
    gallery.open(click({ id: "tea" }));
    gallery.use();
    home.onShow();
    assert.equal(route, "/pages/home/home");
    assert.match(home.data.brief, /抹茶/);
    home.addPhoto();
    for (let i = 0; i < 100 && !home.data.assetImage; i++) await delay(50);
    assert.ok(home.data.assetImage);
    home.acceptPhoto();
    assert.equal(home.data.assetConfirmed, true);
    for (const kind of ["poster", "video", "copy"]) {
      home.changeKind(click({ kind }));
      if (kind === "poster") {
        home.selectFormat({ ...click({ key: "ratio" }), ...input(1) });
        home.selectFormat({ ...click({ key: "dpi" }), ...input(1) });
      }
      if (kind === "video") {
        home.selectFormat({ ...click({ key: "ratio" }), ...input(4) });
        home.selectFormat({ ...click({ key: "resolution" }), ...input(0) });
      }
      await home.preview();
      assert.equal(route, "/pages/confirm/confirm");
      const confirm = page("confirm");
      confirm.onLoad();
      const p = confirm.data.preview;
      assert.equal(p.kind, kind);
      assert.equal(
        p.plan.design?.id,
        kind === "copy" ? undefined : gallery.data.samples[0].style,
      );
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
      for (let i = 0; i < 400; i++) {
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
    }
    const mine = page("mine");
    await mine.load();
    assert.equal(mine.data.works.length, 3);
    assert.equal(mine.data.credits, 104);
    const state = await api.request("state");
    assert.equal(state.assets.length, 1);
    const reopened = page("home");
    reopened.onLoad();
    reopened.changeKind(click({ kind: "poster" }));
    assert.equal(reopened.data.format.ratio, "1:1");
    assert.deepEqual(errors, []);
  },
);
