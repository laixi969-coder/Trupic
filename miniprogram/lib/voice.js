const api = require("./api");

const sampleRate = 16000;
const permissionHelp = "请在小程序右上角的设置中允许使用麦克风，也可以输入文字。";
let recorder, recording, latest, playback;
let draining = false;
let serviceTail = Promise.resolve();
let sequence = 0, fileSequence = 0;

// The server allows one audio operation per workspace. Superseded requests that
// already reached it must finish before a newer recording or reply can enter.
function voiceService(isCurrent, request) {
  const result = serviceTail.then(() => isCurrent() ? request() : undefined);
  serviceTail = result.catch(() => {});
  return result;
}

function filePath(ext) {
  return wx.env.USER_DATA_PATH + "/trupic-voice-" + Date.now() + "-" + ++fileSequence + "." + ext;
}
function removeFile(path) {
  if (!path) return;
  try { wx.getFileSystemManager().unlink({ filePath: path, fail() {} }); } catch (_) {}
}
function fileOperation(method, options) {
  return new Promise((resolve, reject) => wx.getFileSystemManager()[method]({
    ...options, success: resolve, fail: () => reject(new Error("无法读取或保存语音，请重试")),
  }));
}

function wavFromPcm(raw) {
  const pcm = new Uint8Array(raw);
  if (!pcm.length) throw new Error("没有录到声音，请再说一次");
  if (pcm.length >= 44 && pcm[0] === 82 && pcm[1] === 73 && pcm[2] === 70 && pcm[3] === 70)
    return raw;
  const data = new ArrayBuffer(44 + pcm.length), header = new DataView(data);
  function tag(offset, chars) {
    for (let i = 0; i < chars.length; i++) header.setUint8(offset + i, chars.charCodeAt(i));
  }
  tag(0, "RIFF"); header.setUint32(4, 36 + pcm.length, true); tag(8, "WAVE");
  tag(12, "fmt "); header.setUint32(16, 16, true); header.setUint16(20, 1, true);
  header.setUint16(22, 1, true); header.setUint32(24, sampleRate, true);
  header.setUint32(28, sampleRate * 2, true); header.setUint16(32, 2, true);
  header.setUint16(34, 16, true); tag(36, "data"); header.setUint32(40, pcm.length, true);
  new Uint8Array(data, 44).set(pcm);
  return data;
}

function state(turn, value) {
  turn.phase = value;
  if (!turn.owner.disposed) turn.owner.onState(value);
}
function finish(turn, text, error) {
  if (latest !== turn) return;
  latest = null;
  state(turn, "idle");
  // The idle observer can itself open the next turn or dispose the page.
  if (turn.owner.disposed || turn.id !== sequence) return;
  if (error) turn.owner.onError(error);
  else if (text) turn.owner.onText(text);
}
function stopRecorder(turn) {
  turn.stopRequested = true;
  clearTimeout(turn.initialTimer);
  if (recording !== turn || !turn.started || turn.stopping) return;
  turn.stopping = true;
  try { recorder.stop(); }
  catch (_) { releaseRecorder(turn); finish(turn, "", "录音未能正常结束，请再试一次"); }
}
function discard(turn) {
  if (!turn) return;
  if (latest === turn) latest = null;
  if (recording === turn) stopRecorder(turn);
  state(turn, "idle");
}
function releaseRecorder(turn) {
  clearTimeout(turn.initialTimer);
  recording = null;
  // A new recording must wait for the singleton's previous terminal event.
  draining = true;
  setTimeout(() => { draining = false; beginIfReady(); }, 0);
}
async function transcribe(turn, rawPath) {
  let wavPath;
  try {
    if (!rawPath) throw new Error("未收到录音文件，请再说一次");
    state(turn, "transcribing");
    if (latest !== turn) return;
    if (turn.pcm) {
      const raw = await fileOperation("readFile", { filePath: rawPath });
      if (latest !== turn) return;
      wavPath = filePath("wav");
      await fileOperation("writeFile", { filePath: wavPath, data: wavFromPcm(raw.data) });
    }
    if (latest !== turn) return;
    const text = await voiceService(() => latest === turn, () => api.transcribeVoice(wavPath || rawPath));
    finish(turn, text);
  } catch (e) {
    finish(turn, "", e.message || "语音转写失败，请重试");
  } finally {
    removeFile(wavPath);
    removeFile(rawPath);
  }
}
function examineFrame(event) {
  const turn = recording;
  if (!turn || latest !== turn || !turn.pcm || !turn.started || turn.stopRequested || !event.frameBuffer) return;
  const samples = new Int16Array(event.frameBuffer, 0, Math.floor(event.frameBuffer.byteLength / 2));
  if (!samples.length) return;
  let total = 0, squares = 0;
  for (const sample of samples) {
    total += sample;
    squares += sample * sample;
  }
  const mean = total / samples.length;
  const rms = Math.sqrt(Math.max(0, squares / samples.length - mean * mean)) / 32768;
  const ms = samples.length * 1000 / sampleRate;
  turn.sawFrames = true;
  if (rms >= 0.003) turn.hasSignal = true;
  if (rms > Math.max(0.012, turn.noise * 2.8)) {
    turn.voicedMs += ms;
    turn.quietMs = 0;
    if (turn.voicedMs >= 112) turn.heard = true;
  } else {
    turn.voicedMs = 0;
    turn.quietMs += ms;
    if (!turn.heard) turn.noise = Math.min(0.018, turn.noise * 0.92 + rms * 0.08);
    if (turn.heard && turn.quietMs >= 960) stopRecorder(turn);
  }
}
function getRecorder() {
  if (recorder) return recorder;
  const manager = wx.getRecorderManager();
  manager.onStart(() => {
    const turn = recording;
    if (!turn) return;
    turn.started = true;
    if (turn.stopRequested || latest !== turn) { stopRecorder(turn); return; }
    if (turn.pcm) {
      turn.initialTimer = setTimeout(() => {
        if (recording !== turn || turn.heard) return;
        if (turn.sawFrames && !turn.hasSignal) turn.silent = true;
        stopRecorder(turn);
      }, 8000);
    }
    state(turn, "listening");
  });
  manager.onStop((event) => {
    const turn = recording;
    if (!turn) return;
    releaseRecorder(turn);
    if (latest !== turn || turn.silent) {
      removeFile(event.tempFilePath);
      if (turn.silent) finish(turn, "", "没有听到清晰的声音，请再说一次");
      return;
    }
    transcribe(turn, event.tempFilePath);
  });
  manager.onError((error) => {
    const turn = recording;
    if (!turn) return;
    releaseRecorder(turn);
    const denied = /auth|deny|permission/i.test(error && error.errMsg);
    finish(turn, "", denied ? permissionHelp : "麦克风暂时不可用，请检查录音权限后重试");
  });
  if (manager.onFrameRecorded) manager.onFrameRecorded(examineFrame);
  if (manager.onInterruptionBegin) manager.onInterruptionBegin(() => {
    const turn = recording;
    if (!turn) return;
    finish(turn, "", "录音已被其他音频打断，请重新开始");
    stopRecorder(turn);
  });
  recorder = manager;
  return recorder;
}
function beginIfReady() {
  const turn = latest;
  if (!turn || !turn.authorized || recording || draining || turn.phase !== "authorizing") return;
  try {
    const manager = getRecorder();
    turn.pcm = turn.autoStop && typeof manager.onFrameRecorded === "function";
    recording = turn;
    manager.start({
      duration: turn.autoStop ? (turn.pcm ? 45000 : 8000) : 60000,
      sampleRate, numberOfChannels: 1, encodeBitRate: 48000,
      format: turn.pcm ? "PCM" : "mp3", ...(turn.pcm ? { frameSize: 2 } : {}),
    });
  } catch (_) {
    if (recording === turn) releaseRecorder(turn);
    finish(turn, "", "当前微信无法开始录音，请使用文字或稍后重试");
  }
}
function createVoice({ onState = () => {}, onText = () => {}, onError = () => {} } = {}) {
  const owner = { onState, onText, onError, disposed: false };
  return {
    start({ autoStop = false } = {}) {
      if (owner.disposed) return;
      if (latest && latest.owner === owner && latest.phase !== "transcribing" && !latest.stopRequested) return;
      const previous = latest;
      const turn = { id: ++sequence, owner, autoStop, noise: 0.004, quietMs: 0, voicedMs: 0 };
      latest = turn;
      discard(previous);
      if (playback) playback.finish(false);
      if (latest !== turn) return;
      state(turn, "authorizing");
      if (latest !== turn) return;
      try {
        wx.authorize({
          scope: "scope.record",
          success() { if (latest === turn) { turn.authorized = true; beginIfReady(); } },
          fail() { finish(turn, "", permissionHelp); },
        });
      } catch (_) { finish(turn, "", "当前微信无法访问麦克风，可以输入文字。"); }
    },
    stop() {
      if (!latest || latest.owner !== owner) return;
      if (latest.phase === "listening") stopRecorder(latest);
      else discard(latest);
    },
    dispose() {
      owner.disposed = true;
      if (latest && latest.owner === owner) discard(latest);
    },
  };
}

function createSpeaker() {
  const owner = { disposed: false };
  function stop() { if (playback && playback.owner === owner) playback.finish(false); }
  return {
    speak(text) {
      if (owner.disposed || !String(text || "").trim()) return Promise.resolve(false);
      if (playback) playback.finish(false);
      return new Promise((resolve, reject) => {
        let audio, path;
        const run = {
          owner,
          finish(completed, error) {
            if (playback !== run) return;
            playback = null;
            if (audio) {
              try { audio.stop(); } catch (_) {}
              try { audio.destroy(); } catch (_) {}
            }
            removeFile(path);
            if (error) reject(error);
            else resolve(completed);
          },
        };
        playback = run;
        (async () => {
          try {
            const data = await voiceService(() => playback === run, () => api.speakVoice(text.trim()));
            if (playback !== run) return;
            const pendingPath = filePath("mp3");
            // If stopped while writing, clean up only once the write has settled.
            try { await fileOperation("writeFile", { filePath: pendingPath, data }); }
            catch (error) { removeFile(pendingPath); throw error; }
            if (playback !== run) { removeFile(pendingPath); return; }
            path = pendingPath;
            audio = wx.createInnerAudioContext();
            audio.onEnded(() => run.finish(true));
            if (audio.onStop) audio.onStop(() => run.finish(false));
            if (audio.onPause) audio.onPause(() => run.finish(false));
            audio.onError(() => run.finish(false, new Error("朗读播放失败，请重试")));
            audio.src = path;
            audio.play();
          } catch (e) { run.finish(false, e); }
        })();
      });
    },
    stop,
    dispose() { owner.disposed = true; stop(); },
  };
}
module.exports = { createVoice, createSpeaker };
