// The two one-tap entries of the PRD: images with copy, or a short video with copy.
const api = require("../../lib/api");

const modes = [
  { id: "image", name: "图片文字一键" },
  { id: "video", name: "视频文字一键" },
];
const ratios = [
  { key: "square", label: "1:1" },
  { key: "portrait", label: "3:4" },
  { key: "story", label: "9:16" },
  { key: "feed", label: "4:5" },
  { key: "landscape", label: "16:9" },
];
// Every ratio is shown with its number and a shape of the same proportions.
const shapeStyles = ratios.map(({ label }) => {
  const [w, h] = label.split(":").map(Number);
  const scale = 28 / Math.max(w, h);
  return `width:${Math.round(w * scale)}rpx;height:${Math.round(h * scale)}rpx;`;
});
const savedFields = "brief mode imageCount ratioKey videoRatioKey duration facts".split(" ");
const empty = {
  brief: "",
  mode: "image",
  imageCount: 1,
  ratioKey: "portrait",
  videoRatioKey: "story",
  duration: 15,
  facts: "",
};

Page({
  data: {
    ...empty,
    modes,
    ratios,
    shapeStyles,
    prices: null,
    durations: [],
    credits: null,
    asset: null,
    assetConfirmed: false,
    photo: "",
    planning: false,
    plan: null,
    planError: "",
    busy: false,
  },
  onLoad() {
    const draft = wx.getStorageSync("trupic.quick");
    // Drafts saved before the workspace was recorded have no owner and are adopted once.
    this.draftWorkspace = draft?.workspace || null;
    const app = getApp();
    this.setData({ ...empty, ...draft, mode: app.globalData.quickMode || draft?.mode || "image" });
    app.globalData.quickMode = null;
    this.update({ plan: null });
  },
  onShow() {
    // A product photo confirmed in the studio keeps its confirmation here.
    const studio = wx.getStorageSync("trupic.draft");
    if (this.data.asset && studio?.asset?.id === this.data.asset.id)
      this.setData({ assetConfirmed: !!studio.assetConfirmed });
    return this.load();
  },
  async load() {
    try {
      const state = await api.request("state");
      if (this.draftWorkspace === null) this.draftWorkspace = state.workspace;
      // Another account on this device must not inherit the earlier brief or product photo.
      if (this.draftWorkspace !== state.workspace) {
        this.draftWorkspace = state.workspace;
        wx.setStorageSync("trupic.quick", null);
        this.setData({ ...empty, asset: null, assetConfirmed: false });
      }
      this.update({ prices: state.prices, durations: state.videoDurations, credits: state.credits });
      this.setData({ trialNote: state.trialNote || "" });
    } catch (e) {
      this.setData({ planError: e.message, prices: null });
    }
  },
  // Recompute the request, the shown prices and a fresh plan after any change.
  update(fields) {
    this.setData(fields);
    const { mode, prices, durations } = this.data;
    const image = mode === "image";
    const cost = (n) => prices.copy + (image ? prices.poster * n : prices["video" + (n > 15 ? n : "")]);
    const duration = durations.includes(this.data.duration) ? this.data.duration : 15;
    this.setData({
      duration,
      imageCosts: prices ? [1, 2].map(cost) : null,
      videoCosts: prices ? durations.map(cost) : null,
      total: prices ? cost(image ? this.data.imageCount : duration) : null,
    });
    this.save();
    return this.replan();
  },
  save() {
    const draft = { workspace: this.draftWorkspace || undefined };
    for (const key of savedFields) draft[key] = this.data[key];
    wx.setStorageSync("trupic.quick", draft);
  },
  request() {
    const d = this.data;
    return {
      deliveryMode: d.mode,
      ratio: d.mode === "video" ? d.videoRatioKey : d.ratioKey,
      imageCount: d.mode === "image" ? d.imageCount : undefined,
      duration: d.mode === "video" ? d.duration : undefined,
      brief: d.brief,
      facts: d.facts,
      asset: d.asset ? d.asset.id : "",
      assetMode: "original",
      assetConfirmed: d.assetConfirmed,
      source: "一键创作",
    };
  },
  async replan() {
    const request = this.request();
    const version = (this.planRequest = (this.planRequest || 0) + 1);
    this.setData({ plan: null, planError: "" });
    if (request.brief.trim().length < 2) return this.setData({ planning: false });
    this.setData({ planning: true });
    try {
      const plan = await api.request("creations/plan", "POST", request);
      if (version === this.planRequest)
        this.setData({ plan, planning: false, delivery: (plan.deliveries || []).map((d) => d.label).join("、") });
    } catch (e) {
      if (version === this.planRequest) this.setData({ planning: false, planError: e.message });
    }
  },
  input(e) {
    this.setData({ brief: e.detail.value });
    this.save();
    return this.replan();
  },
  facts(e) {
    this.setData({ facts: e.detail.value });
    this.save();
    return this.replan();
  },
  pick(e) {
    const { key, value } = e.currentTarget.dataset;
    return this.update({ [key]: key === "imageCount" || key === "duration" ? Number(value) : value });
  },
  addPhoto() {
    if (this.data.busy) return;
    wx.chooseMedia({
      count: 1,
      mediaType: ["image"],
      sourceType: ["album", "camera"],
      success: async (r) => {
        this.setData({ busy: true });
        try {
          const file = r.tempFiles[0].tempFilePath;
          const asset = await api.upload(file);
          this.setData({ asset, assetConfirmed: false, photo: file });
          await this.replan();
        } catch (e) {
          api.message(e);
        } finally {
          this.setData({ busy: false });
        }
      },
    });
  },
  removePhoto() {
    this.setData({ asset: null, assetConfirmed: false, photo: "" });
    return this.replan();
  },
  // Marking a protected label needs the studio's tools; hand the photo and brief over.
  toStudio() {
    const { brief, asset } = this.data;
    getApp().globalData.handoff = { brief, asset };
    wx.switchTab({ url: "/pages/home/home" });
  },
  history() {
    wx.switchTab({ url: "/pages/mine/mine" });
  },
  go() {
    const { plan } = this.data;
    if (!plan?.ready || this.data.planning || this.data.busy) return;
    const request = JSON.stringify(this.request());
    if (this.keyFor !== request) {
      this.keyFor = request;
      this.requestKey = "wx-" + Date.now() + "-" + Math.random().toString(36).slice(2);
    }
    getApp().globalData.quickPlan = { plan, requestKey: this.requestKey, cost: this.data.total };
    wx.navigateTo({ url: "/pages/quick-confirm/quick-confirm" });
  },
});
