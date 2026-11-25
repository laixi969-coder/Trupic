const api = require("../../lib/api");
const { createVoice } = require("../../lib/voice");

const emptyDraft = {
  homeText: "",
  homeHasText: false,
  homePhoto: "",
  homeAsset: null,
  homePhotoError: "",
  homeUploading: false,
  homeError: "",
};
const voiceLabels = {
  idle: "说需求",
  authorizing: "授权中",
  listening: "说完了",
  transcribing: "转写中",
};
const pendingLabels = {
  planning: ["正在规划", "查看任务"],
  queued: ["排队中", "查看进度"],
  running: ["正在制作", "查看进度"],
  reviewing: ["正在审核", "查看进度"],
  waiting_input: ["需要补充", "补充需求"],
  waiting_copy: ["待选文案", "去选文案"],
  waiting_script: ["待核对脚本", "查看脚本"],
  quoted: ["等待确认", "核对报价"],
};

module.exports = {
  data: {
    ...emptyDraft,
    homeVerified: false,
    homePending: null,
    homePendingState: "loading",
    homeVoiceState: "idle",
    homeVoiceLabel: voiceLabels.idle,
    homeNavigating: false,
  },
  methods: {
    homeIsReady() {
      return this.homeVisible && this.data.homeVerified && this.data.personalAgent &&
        !this.data.studio && !this.data.legacyMoment && !this.data.homeNavigating;
    },
    resetHomeAccount() {
      this.endHomeVoice();
      this.homePhotoPicker = null;
      this.homePhotoVersion = (this.homePhotoVersion || 0) + 1;
      this.homeSummaryVersion = (this.homeSummaryVersion || 0) + 1;
      this.setData({ ...emptyDraft, homePending: null, homePendingState: "loading", legacyMoment: false });
    },
    startHomeVoiceController() {
      if (!this.homeIsReady() || this.homeVoice) return;
      const owner = this.workspace;
      const active = () => this.homeVoice === control && owner === this.workspace && this.homeIsReady();
      const control = createVoice({
        onState: (state) => {
          if (active()) this.setData({ homeVoiceState: state, homeVoiceLabel: voiceLabels[state] });
        },
        onText: (text) => {
          if (!active() || !String(text || "").trim()) return;
          const before = this.data.homeText.trimEnd();
          const addition = String(text).trim();
          const combined = before ? before + "\n" + addition : addition;
          this.setData({
            homeText: combined.slice(0, 1200),
            homeHasText: true,
            homeError: combined.length > 1200 ? "需求最长 1200 字，请核对后发送。" : "",
          });
        },
        onError: (err) => {
          if (active()) this.setData({ homeError: err?.message || String(err || "未能听清，请再试一次或直接打字。") });
        },
      });
      this.homeVoice = control;
    },
    endHomeVoice() {
      const voice = this.homeVoice;
      this.homeVoice = null;
      if (voice) voice.dispose();
      if (this.data.homeVoiceState !== "idle")
        this.setData({ homeVoiceState: "idle", homeVoiceLabel: voiceLabels.idle });
    },
    toggleHomeVoice() {
      if (!this.homeIsReady()) return;
      if (this.data.homeVoiceState === "listening") return this.homeVoice?.stop();
      if (this.data.homeVoiceState !== "idle") return;
      this.setData({ homeError: "" });
      this.startHomeVoiceController();
      this.homeVoice?.start();
    },
    homeInput(e) {
      if (!this.homeIsReady()) return;
      const homeText = e.detail.value;
      this.setData({ homeText, homeHasText: !!homeText.trim(), homeError: "" });
    },
    async loadHomePending() {
      if (!this.homeIsReady()) return;
      const owner = this.workspace;
      const revision = (this.homeSummaryVersion || 0) + 1;
      this.homeSummaryVersion = revision;
      const current = () => this.homeIsReady() && this.workspace === owner && this.homeSummaryVersion === revision;
      this.setData({ homePendingState: "loading" });
      try {
        const result = await api.request("agent");
        if (!current()) return;
        if (result.workspace !== owner) {
          // The account changed while this page was open. Recheck before showing private data.
          this.setData({ homeVerified: false, homePending: null, momentError: "工作区已切换，请重新连接。" });
          return;
        }
        const pending = result.pending;
        const labels = pending && pendingLabels[pending.status];
        const homePending = pending?.conversation && pending.task && labels ? {
          ...pending, label: labels[0], action: labels[1],
          showCost: pending.status === "quoted" && typeof pending.cost === "number",
        } : null;
        this.setData({ homePending, homePendingState: "ready" });
      } catch (_) {
        if (current()) this.setData({ homePending: null, homePendingState: "error" });
      }
    },
    pickHomePhoto() {
      if (!this.homeIsReady() || this.data.homeVoiceState !== "idle" || this.homePhotoPicker) return;
      const owner = this.workspace;
      const picker = {};
      this.homePhotoPicker = picker;
      wx.chooseMedia({
        count: 1, mediaType: ["image"], sourceType: ["camera", "album"], sizeType: ["compressed"],
        success: ({ tempFiles }) => {
          if (this.homePhotoPicker !== picker || owner !== this.workspace || this.homeDestroyed) return;
          const file = tempFiles?.[0]?.tempFilePath;
          if (!file) return;
          this.setData({ homePhoto: file, homeAsset: null, homePhotoError: "", homeError: "" });
          return this.uploadHomePhoto();
        },
        fail: (err) => {
          if (this.homePhotoPicker === picker && owner === this.workspace && !this.homeDestroyed && !/cancel/i.test(err?.errMsg || ""))
            this.setData({ homeError: "无法打开相机或相册，请检查微信权限后重试。" });
        },
        complete: () => { if (this.homePhotoPicker === picker) this.homePhotoPicker = null; },
      });
    },
    async uploadHomePhoto() {
      const path = this.data.homePhoto;
      if (!path || !this.workspace) return;
      const owner = this.workspace;
      const revision = (this.homePhotoVersion || 0) + 1;
      this.homePhotoVersion = revision;
      const current = () => !this.homeDestroyed && this.workspace === owner && this.homePhotoVersion === revision;
      this.setData({ homeUploading: true, homePhotoError: "", homeAsset: null });
      try {
        const asset = await api.upload(path);
        if (current()) this.setData({ homeAsset: asset });
      } catch (err) {
        if (current()) this.setData({ homePhotoError: err.message || "商品图未能上传。" });
      } finally {
        if (current()) this.setData({ homeUploading: false });
      }
    },
    previewHomePhoto() {
      const path = this.data.homePhoto;
      if (this.homeIsReady() && path && this.data.homeVoiceState === "idle") wx.previewImage({ current: path, urls: [path] });
    },
    removeHomePhoto() {
      if (!this.homeIsReady()) return;
      this.homePhotoVersion = (this.homePhotoVersion || 0) + 1;
      this.setData({ homePhoto: "", homeAsset: null, homeUploading: false, homePhotoError: "", homeError: "" });
    },
    openHomeAgent(query, entry) {
      if (!this.homeIsReady() || this.data.homeVoiceState !== "idle") return;
      const shared = getApp().globalData;
      if (entry) shared.agentEntry = entry;
      this.setData({ homeNavigating: true, homeError: "" });
      wx.navigateTo({
        url: "/pages/agent/agent?" + query,
        success: () => {
          if (entry && this.workspace === entry.workspace) this.setData({ ...emptyDraft });
        },
        fail: () => {
          if (entry && shared.agentEntry === entry) shared.agentEntry = null;
          this.setData({ homeNavigating: false, homeError: "未能打开对话，请重试。" });
        },
      });
    },
    sendHome() {
      const text = this.data.homeText.trim() || (this.data.homeAsset ? "用这张商品图做一张海报。" : "");
      if (!text || this.data.homeUploading || (this.data.homePhoto && !this.data.homeAsset)) return;
      this.openHomeAgent("mode=new", { workspace: this.workspace, text, asset: this.data.homeAsset, photo: this.data.homePhoto, send: true });
    },
    homeCall() {
      if (this.data.homeUploading || (this.data.homePhoto && !this.data.homeAsset)) return;
      const text = this.data.homeText.trim(), asset = this.data.homeAsset;
      this.openHomeAgent("mode=call", text || asset ? { workspace: this.workspace, text, asset, photo: this.data.homePhoto, send: false } : null);
    },
    homeHistory() { this.openHomeAgent("mode=history"); },
    homeResume() {
      const row = this.data.homePending;
      if (row) this.openHomeAgent("conversation=" + encodeURIComponent(row.conversation) + "&task=" + encodeURIComponent(row.task));
    },
    showAssistant() {
      this.setData({ studio: false, legacyMoment: false });
      this.startHomeVoiceController();
      return this.loadHomePending();
    },
    showLegacy() {
      if (this.data.homeVoiceState !== "idle") return;
      this.endHomeVoice();
      this.setData({ legacyMoment: true });
    },
  },
};
