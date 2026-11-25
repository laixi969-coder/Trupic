const { createVoice, createSpeaker } = require("./voice");

const recordingLabels = {
  idle: "",
  authorizing: "正在打开麦克风",
  listening: "正在听",
  transcribing: "正在转写",
};

function spokenReply(turns) {
  const last = turns.slice().reverse().find((item) => item.role === "assistant");
  if (!last) return "";
  if (last.kind === "task" && last.card) {
    const card = last.card;
    if (card.status === "quoted")
      return "本次制作需要" + card.cost + "积分。核对定稿后，请点确认制作。";
    if (card.status === "waiting_copy") {
      return card.options.length
        ? "请选择文案。" + card.options.map((item, i) => "第" + (i + 1) + "组，" + item.title).join("。")
        : "需要先选文案，请点获取候选文案。";
    }
    return card.note || card.stateText || "";
  }
  if (last.kind === "topics") return "本周可以试试这些主题。" + last.items.map((i) => i.title).join("。");
  if (last.kind === "switch") return "这是一个新任务。请在屏幕上选另开对话或留在这里。";
  return last.text || "";
}

async function readAll(speaker, text) {
  let rest = Array.from(text);
  while (rest.length) {
    let count = Math.min(600, rest.length);
    if (rest.length > count) {
      for (let i = count - 1; i >= 300; i--) {
        if ("。！？；，\n".includes(rest[i])) { count = i + 1; break; }
      }
    }
    if (!(await speaker.speak(rest.splice(0, count).join("")))) return false;
  }
  return true;
}

module.exports = {
  data: { callActive: false, voiceState: "idle", voiceNote: "", speaking: false },
  methods: {
    setupAudio() {
      this.switchAudioOff();
      this.mic = createVoice({
        onState: (voiceState) => {
          if (this.visible) this.setData({ voiceState, voiceNote: recordingLabels[voiceState] || "" });
        },
        onError: (message) => {
          if (!this.visible) return;
          this.switchAudioOff();
          this.setData({ voiceNote: message });
        },
        onText: (text) => {
          if (!this.visible || !text.trim()) return;
          if (this.data.callActive) {
            this.continueCall(text);
          } else {
            this.setData({ text: (this.data.text + text).slice(0, 1200), voiceNote: "已转成文字，核对后发送。" });
          }
        },
      });
      this.speaker = createSpeaker();
    },
    switchAudioOff() {
      this.audioRound = (this.audioRound || 0) + 1;
      if (this.mic) this.mic.dispose();
      if (this.speaker) this.speaker.dispose();
      this.mic = null;
      this.speaker = null;
      this.setData({ callActive: false, speaking: false, voiceState: "idle", voiceNote: "" });
    },
    dictate() {
      if (this.data.callActive || this.data.busy || this.data.speaking) return;
      if (!this.mic) this.setupAudio();
      if (this.data.voiceState === "listening") return this.mic.stop();
      if (this.data.voiceState === "idle") return this.mic.start();
    },
    toggleCall() {
      if (this.data.callActive) {
        this.switchAudioOff();
        this.setData({ voiceNote: "语音对话已结束。" });
        return;
      }
      if (this.data.busy || this.data.voiceState !== "idle") return;
      this.setupAudio();
      this.setData({ callActive: true, error: "" });
      return this.mic.start({ autoStop: true });
    },
    async continueCall(text) {
      const round = this.audioRound;
      const active = () => this.visible && this.audioRound === round && this.data.callActive;
      const phrase = text.trim().slice(0, 1200);
      if (!active() || !phrase) return;
      this.setData({ voiceNote: "已听到，正在等助理回复…" });
      const response = await this.sendText(phrase, {}, { preserveDraft: true });
      if (!active()) return;
      if (!response) {
        this.switchAudioOff();
        this.setData({
          text: (this.data.text + phrase).slice(0, 1200),
          voiceNote: "这次没有收到回复，语音已保留在草稿中。",
        });
        return;
      }
      try {
        const last = this.data.turns[this.data.turns.length - 1];
        if (last?.card?.status === "waiting_copy" && !last.card.options.length) {
          this.setData({ voiceNote: "正在准备候选文案…" });
          await this.loadSpokenChoices(response.id, last.card, active);
          if (!active()) return;
        }
        const reply = spokenReply(this.data.turns);
        if (reply) {
          this.setData({ speaking: true, voiceNote: "助理正在回复…" });
          const completed = await readAll(this.speaker, reply);
          if (active() && !completed) {
            this.switchAudioOff();
            this.setData({ voiceNote: "播放已中断，语音对话已结束。" });
            return;
          }
        }
        if (active()) {
          this.setData({ speaking: false });
          await this.mic.start({ autoStop: true });
        }
      } catch (e) {
        if (!active()) return;
        this.switchAudioOff();
        this.setData({ voiceNote: e.message || "播报中断，可以查看文字回复。" });
      }
    },
    async readReply() {
      if (this.data.speaking) return this.switchAudioOff();
      if (this.data.busy || this.data.callActive || this.data.voiceState !== "idle") return;
      const reply = spokenReply(this.data.turns);
      if (!reply) return;
      this.setupAudio();
      const round = this.audioRound;
      this.setData({ speaking: true, voiceNote: "正在朗读回复…" });
      try {
        await readAll(this.speaker, reply);
        if (round === this.audioRound) this.setData({ speaking: false, voiceNote: "" });
      } catch (e) {
        if (round === this.audioRound)
          this.setData({ speaking: false, voiceNote: e.message || "播报中断，可以重试。" });
      }
    },
  },
};
