const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { setTimeout: delay } = require("node:timers/promises");
const next = () => delay(5);
const root = path.resolve(__dirname, "../miniprogram");

function harness({ frames = true, timeout = setTimeout } = {}) {
  const calls = { auth: [], uploads: [], requests: [], starts: [], removes: [], players: [], writes: [] };
  const files = new Map(), storage = new Map(), handlers = {};
  let managers = 0, stops = 0, autoWrite = true;
  const manager = {
    start(o) { calls.starts.push(o); },
    stop() { stops++; },
  };
  for (const type of ["Start", "Stop", "Error", "FrameRecorded", "InterruptionBegin"]) {
    if (!frames && type === "FrameRecorded") continue;
    manager["on" + type] = fn => {
      assert.ok(!handlers[type], "one global listener per native event");
      handlers[type] = fn;
    };
  }
  const filesystem = {
    readFile(o) { o.success({ data: files.get(o.filePath) }); },
    writeFile(o) { calls.writes.push(o); if (autoWrite) { files.set(o.filePath, o.data); o.success(); } },
    unlink(o) { calls.removes.push(o.filePath); files.delete(o.filePath); },
  };
  const wx = {
    env: { USER_DATA_PATH: "/user" },
    authorize(o) { calls.auth.push(o); },
    getRecorderManager() { managers++; return manager; },
    getFileSystemManager: () => filesystem,
    getAccountInfoSync: () => ({ miniProgram: { envVersion: "develop" } }),
    getStorageSync: key => storage.get(key),
    setStorageSync: (key, value) => storage.set(key, value),
    request(o) {
      if (o.url.endsWith("/api/state"))
        return o.success({ statusCode: 200, data: {}, cookies: ["trupic_workspace=here; HttpOnly"] });
      calls.requests.push(o);
    },
    uploadFile: o => calls.uploads.push(o),
    createInnerAudioContext() {
      const player = { plays: 0, stops: 0, destroys: 0,
        onEnded(fn) { this.end = fn; }, onError(fn) { this.fail = fn; },
        onStop(fn) { this.stopped = fn; }, onPause(fn) { this.paused = fn; },
        play() { this.plays++; }, stop() { this.stops++; this.stopped(); }, destroy() { this.destroys++; },
      };
      calls.players.push(player); return player;
    },
  };
  const loaded = new Map();
  function load(file) {
    if (loaded.has(file)) return loaded.get(file);
    const module = { exports: {} };
    vm.runInNewContext(fs.readFileSync(file, "utf8"), {
      module, wx, setTimeout: timeout, clearTimeout,
      require: id => load(path.resolve(path.dirname(file), id + ".js")),
    }, { filename: file });
    loaded.set(file, module.exports);
    return module.exports;
  }
  const lib = load(path.join(root, "lib/voice.js"));
  function voice() {
    const events = [];
    const controller = lib.createVoice({
      onState: value => events.push(value),
      onText: text => events.push("text:" + text),
      onError: msg => events.push("error:" + msg),
    });
    return { controller, events };
  }
  function started(voice, options) {
    voice.controller.start(options);
    calls.auth.at(-1).success();
    handlers.Start();
  }
  return { calls, files, handlers, voice, started, lib,
    managers: () => managers, stops: () => stops, holdWrites: () => { autoWrite = false; } };
}
const success = (call, data) => call.success({ statusCode: 200, data });

test("权限由用户启动触发，拒绝和迟到的授权回调都不会开启录音", () => {
  const h = harness(), a = h.voice(), b = h.voice(), s = h.lib.createSpeaker();
  assert.equal(h.managers(), 0); assert.equal(h.calls.auth.length, 0);
  a.controller.start(); a.controller.start();
  assert.equal(h.calls.auth.length, 1);
  assert.equal(h.calls.auth[0].scope, "scope.record");
  h.calls.auth[0].fail({});
  assert.deepEqual(a.events.slice(0, 2), ["authorizing", "idle"]);
  assert.match(a.events[2], /设置.*麦克风/);
  a.controller.start(); b.controller.start();
  h.calls.auth[1].success(); b.controller.dispose(); h.calls.auth[2].success();
  assert.equal(h.managers(), 0);
  assert.equal(h.calls.uploads.length, 0);
  s.dispose();
});

test("切页后共享录音器串行交接，旧 stop 和错误转写不能污染新的轮次", async () => {
  const h = harness(), a = h.voice(), b = h.voice();
  h.started(a); a.controller.dispose();
  b.controller.start(); h.calls.auth[1].success();
  assert.equal(h.calls.starts.length, 1);
  h.handlers.Stop({ tempFilePath: "/temp/old.mp3" }); await next();
  assert.equal(h.managers(), 1); assert.equal(h.calls.starts.length, 2);
  assert.equal(h.calls.uploads.length, 0); assert.ok(h.calls.removes.includes("/temp/old.mp3"));
  h.handlers.Start(); b.controller.stop(); h.handlers.Stop({ tempFilePath: "/temp/b.mp3" }); await next();
  const u1 = h.calls.uploads[0];
  assert.match(u1.url, /\/api\/agent\/voice\/transcribe$/);
  assert.equal(u1.header.Cookie, "trupic_workspace=here");
  assert.equal(u1.name, "audio"); assert.equal(u1.filePath, "/temp/b.mp3");
  h.started(b); b.controller.stop(); h.handlers.Stop({ tempFilePath: "/temp/c.mp3" }); await next();
  assert.equal(h.calls.uploads.length, 1, "the server still has the old audio job");
  u1.fail({}); await next();
  success(h.calls.uploads[1], '{"text":"  新一轮  "}'); await next();
  assert.deepEqual(b.events.slice(-2), ["idle", "text:新一轮"]);
  assert.equal(b.events.filter(v => v.startsWith("text:")).length, 1);
  assert.equal(b.events.filter(v => v.startsWith("error:")).length, 0);
  assert.ok(h.calls.removes.includes("/temp/b.mp3"));
  h.started(b); b.controller.stop(); h.handlers.Stop({ tempFilePath: "/temp/d.mp3" }); await next();
  b.controller.dispose(); success(h.calls.uploads[2], '{"text":"迟到"}'); await next();
  assert.equal(b.events.includes("text:迟到"), false);
});

test("起录未就绪时取消与快速开始下一轮，停止等待原生 onStart 和 onStop", async () => {
  const h = harness(), a = h.voice(), b = h.voice();
  a.controller.start(); h.calls.auth[0].success();
  a.controller.dispose();
  b.controller.start(); h.calls.auth[1].success();
  assert.equal(h.stops(), 0);
  h.handlers.Start(); assert.equal(h.stops(), 1);
  h.handlers.Stop({ tempFilePath: "/temp/unused" }); await next(); h.handlers.Start();
  b.controller.stop(); b.controller.start(); h.calls.auth[2].success();
  assert.equal(h.calls.starts.length, 2); h.handlers.Stop({ tempFilePath: "/temp/older" }); await next();
  assert.equal(h.calls.starts.length, 3); h.handlers.Start();
  h.handlers.InterruptionBegin(); h.handlers.Stop({ tempFilePath: "/temp/call" }); await next();
  assert.equal(h.calls.uploads.length, 0);
  assert.match(b.events.at(-1), /打断/);
});

test("连续模式根据 PCM 话音之后的静默收声，上传有 RIFF 头的单声道 WAV", async () => {
  const h = harness(), a = h.voice(); h.started(a, { autoStop: true });
  const opts = h.calls.starts[0];
  assert.equal(opts.format, "PCM"); assert.equal(opts.sampleRate, 16000);
  assert.equal(opts.numberOfChannels, 1); assert.equal(opts.frameSize, 2);
  const quiet = new Int16Array(1024).buffer, speech = Int16Array.from({ length: 1024 }, (_, i) => 3000 * Math.sin(i / 6)).buffer;
  for (let i = 0; i < 18; i++) h.handlers.FrameRecorded({ frameBuffer: quiet });
  assert.equal(h.stops(), 0);
  for (const buffer of [speech, speech, quiet, speech]) h.handlers.FrameRecorded({ frameBuffer: buffer });
  for (let i = 0; i < 14; i++) h.handlers.FrameRecorded({ frameBuffer: quiet });
  assert.equal(h.stops(), 0);
  h.handlers.FrameRecorded({ frameBuffer: quiet }); assert.equal(h.stops(), 1);
  h.files.set("/temp/raw", speech); h.handlers.Stop({ tempFilePath: "/temp/raw" }); await next();
  const upload = h.calls.uploads[0], wav = Buffer.from(h.files.get(upload.filePath));
  assert.match(upload.filePath, /\.wav$/); assert.equal(wav.toString("ascii", 0, 4), "RIFF");
  assert.equal(wav.readUInt32LE(24), 16000); assert.equal(wav.readUInt16LE(22), 1);
  assert.equal(wav.readUInt16LE(34), 16); assert.deepEqual(wav.subarray(44), Buffer.from(speech));
  success(upload, '{"text":"你好"}'); await next();
  assert.ok(h.calls.removes.includes(upload.filePath)); assert.ok(h.calls.removes.includes("/temp/raw"));
  assert.deepEqual(a.events.slice(-2), ["idle", "text:你好"]);
});

test("无帧支持时限时收声；有帧但环境一直静默时不提交空音频", async () => {
  const old = harness({ frames: false }), m = old.voice();
  old.started(m, { autoStop: true });
  assert.equal(old.calls.starts[0].format, "mp3");
  assert.equal(old.calls.starts[0].duration, 8000);
  m.controller.dispose();
  old.handlers.Stop({ tempFilePath: "/temp/old" });

  let timeout;
  const h = harness({ timeout: (fn, ms) => {
    if (ms === 8000) { timeout = fn; return; }
    return setTimeout(fn, ms);
  } }), a = h.voice();
  h.started(a, { autoStop: true }); h.handlers.FrameRecorded({ frameBuffer: new Int16Array(1024).buffer });
  timeout(); assert.equal(h.stops(), 1);
  h.handlers.Stop({ tempFilePath: "/temp/silent" }); await next();
  assert.equal(h.calls.uploads.length, 0); assert.ok(h.calls.removes.includes("/temp/silent"));
  assert.match(a.events.at(-1), /没有听到/);
});

test("朗读的新轮次优先，中断等待、播放结束和切页都清理临时音频", async () => {
  const h = harness(), a = h.lib.createSpeaker(), b = h.lib.createSpeaker();
  const first = a.speak("第一轮"); await next();
  const second = b.speak("第二轮"); assert.equal(await first, false); await next();
  const bytes = Uint8Array.of(0x49, 0x44, 0x33).buffer;
  assert.equal(h.calls.requests.length, 1);
  success(h.calls.requests[0], bytes); await next();
  const r2 = h.calls.requests[1];
  assert.equal(r2.data.text, "第二轮"); assert.equal(r2.responseType, "arraybuffer");
  assert.match(r2.url, /\/api\/agent\/voice\/speak$/);
  assert.equal(r2.header.Cookie, "trupic_workspace=here");
  success(r2, bytes); await next();
  assert.equal(h.calls.players.length, 1); const player = h.calls.players[0];
  assert.equal(player.plays, 1); assert.ok(h.files.has(player.src));
  a.stop(); assert.equal(player.destroys, 0);
  player.end(); assert.equal(await second, true); assert.equal(player.destroys, 1);
  assert.ok(!h.files.has(player.src));
  const third = b.speak("中断"); await next(); success(h.calls.requests[2], bytes); await next();
  const thirdPlayer = h.calls.players[1]; h.voice().controller.start();
  assert.equal(await third, false); assert.equal(thirdPlayer.destroys, 1);
  h.holdWrites(); const fourth = b.speak("切页"); await next();
  success(h.calls.requests[3], bytes); await next();
  const write = h.calls.writes.at(-1); b.dispose(); assert.equal(await fourth, false);
  h.files.set(write.filePath, write.data); write.success(); await next();
  assert.ok(!h.files.has(write.filePath)); assert.equal(h.calls.players.length, 2);
  assert.equal(await b.speak("卸载后"), false);
});

test("朗读服务返回二进制 JSON 错误时保留后端说明", async () => {
  const h = harness(), speaker = h.lib.createSpeaker();
  const result = speaker.speak("你好"); await next();
  const data = new TextEncoder().encode('{"error":"朗读服务未配置"}').buffer;
  h.calls.requests[0].success({ statusCode: 503, data });
  await assert.rejects(result, /朗读服务未配置/);
  assert.equal(h.calls.players.length, 0);
});
