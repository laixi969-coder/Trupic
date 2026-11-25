const api = require("../../lib/api");
const { confirmBriefChange } = require("../../lib/draft");
const moment = require("../../lib/moment");
const samples = require("../../lib/samples");
const assistant = require("./assistant");
const kinds = [
  { id: "poster", name: "海报" },
  { id: "copy", name: "文案" },
  { id: "video", name: "短片" },
];
const ratios = ["3:4", "1:1", "9:16", "4:5", "16:9"];
const ratioKeys = ["portrait", "square", "story", "feed", "landscape"];
const resolutions = [720, 1080, 2160],
  dpis = [72, 150, 300];
// Every ratio is shown with its number and a shape of the same proportions.
const shapeStyles = ratios.map((label) => {
  const [w, h] = label.split(":").map(Number);
  const scale = 28 / Math.max(w, h);
  return `width:${Math.round(w * scale)}rpx;height:${Math.round(h * scale)}rpx;`;
});
const defaults = {
  poster: { ratio: "3:4", resolution: 1080, dpi: 300 },
  video: { ratio: "9:16", resolution: 720, dpi: 300 },
};
const emptyStudioDraft = {
  kind: "poster",
  brief: "",
  briefError: "",
  focusBrief: false,
  style: "auto",
  source: "一句话创作",
  topicId: "",
  format: defaults.poster,
  asset: null,
  identityRegion: null,
  visualDetail: null,
  assetMode: "original",
  assetConfirmed: false,
  assetImage: "",
  photoError: "",
  sheet: "",
  regionStyle: "",
};
Page({
  ...moment.methods,
  ...assistant.methods,
  data: {
    ...moment.data,
    ...assistant.data,
    studio: false,
    kinds,
    ratios,
    shapeStyles,
    resolutions,
    dpis,
    kind: "poster",
    brief: "",
    briefError: "",
    focusBrief: false,
    style: "auto",
    source: "一句话创作",
    topicId: "",
    topics: [],
    topicsError: "",
    format: defaults.poster,
    asset: null,
    identityRegion: null,
    visualDetail: null,
    assetMode: "original",
    assetConfirmed: false,
    assetImage: "",
    photoError: "",
    uploading: false,
    sheet: "",
    busy: false,
    samples,
  },
  onLoad() {
    this.formats = Object.assign(
      {},
      defaults,
      wx.getStorageSync("trupic.formats") || {},
    );
    const draft = wx.getStorageSync("trupic.draft");
    if (draft)
      this.setData({
        ...draft,
        regionStyle: this.regionStyle(draft.identityRegion),
      });
    // Drafts saved before accounts were recorded have no owner and are adopted once.
    this.draftWorkspace = draft?.workspace || null;
    this.setData({ format: this.formats[this.data.kind] || defaults.poster });
  },
  async onShow() {
    this.homeVisible = true;
    this.homeDestroyed = false;
    const visit = (this.homeVisit || 0) + 1;
    this.homeVisit = visit;
    this.setData({ homeVerified: false, homeNavigating: false, momentError: "" });
    const price = await this.loadMoment();
    if (this.homeVisit !== visit || !this.homeVisible || !price) return;
    this.setData({ homeVerified: true });
    const app = getApp();
    const handoff = app.globalData.handoff;
    if (handoff) {
      // A photo that needs its protected label marked arrives from the one-tap page.
      app.globalData.handoff = null;
      this.setData({
        studio: true,
        kind: "poster",
        brief: handoff.brief,
        briefError: "",
        style: "auto",
        source: "一键创作",
        topicId: "",
        format: this.formats.poster,
        asset: handoff.asset,
        identityRegion: null,
        visualDetail: null,
        regionStyle: "",
        marking: false,
        assetMode: "original",
        assetConfirmed: false,
        assetImage: "",
      });
      this.save();
      await this.showPhoto();
    }
    if (app.globalData.sample) {
      const s = app.globalData.sample;
      this.setData({
        studio: true,
        kind: "poster",
        brief: s.brief,
        briefError: "",
        style: s.style,
        source: "灵感选集 · " + s.name,
        topicId: "",
        format: this.formats.poster,
      });
      app.globalData.sample = null;
      this.save();
      wx.pageScrollTo({ scrollTop: 0, duration: 0 });
    }
    if (this.homeVisit !== visit || !this.homeVisible) return;
    if (this.data.studio) return this.loadTopics();
    this.startHomeVoiceController();
    return this.loadHomePending();
  },
  onHide() {
    this.homeVisible = false;
    this.homeVisit = (this.homeVisit || 0) + 1;
    this.momentLoadVersion = (this.momentLoadVersion || 0) + 1;
    this.endHomeVoice();
    this.setData({ homeVerified: false });
  },
  onUnload() {
    this.homeDestroyed = true;
    this.onHide();
  },
  quick(e) {
    getApp().globalData.quickMode = e.currentTarget.dataset.mode;
    wx.navigateTo({ url: "/pages/quick/quick" });
  },
  adoptWorkspace(workspace) {
    if (this.workspace && this.workspace !== workspace) {
      this.resetHomeAccount();
      this.topicRequest = (this.topicRequest || 0) + 1;
      this.photoRequest = (this.photoRequest || 0) + 1;
      this.setData({ busy: false, uploading: false });
    }
    this.workspace = workspace;
    if (this.draftWorkspace === null) this.draftWorkspace = workspace;
    if (this.draftWorkspace !== workspace) this.resetStudioDraft();
  },
  // Another account on this device must not inherit the earlier brief and product photo.
  resetStudioDraft() {
    this.draftWorkspace = this.workspace;
    wx.setStorageSync("trupic.draft", null);
    this.setData({
      ...emptyStudioDraft,
      format: this.formats.poster,
      topics: [],
      topicsError: "",
    });
  },
  toggleStudio() {
    if (this.data.busy) return;
    this.setData({
      studio: !this.data.studio,
      ...(this.data.studio && this.data.personalAgent ? { legacyMoment: true } : {}),
    });
    return this.data.studio ? this.loadTopics() : this.loadMoment();
  },
  async loadTopics() {
    const request = (this.topicRequest || 0) + 1;
    this.topicRequest = request;
    try {
      const topics = await api.request("topics");
      if (request === this.topicRequest)
        this.setData({ topics: topics.slice(0, 2), topicsError: "" });
    } catch (e) {
      if (request === this.topicRequest)
        this.setData({ topicsError: e.message });
    }
  },
  useTopic(e) {
    const topic = this.data.topics.find(
      (t) => t.topicId === e.currentTarget.dataset.id,
    );
    if (!topic) return;
    confirmBriefChange(this.data.brief, topic.brief, () => {
      this.setData({
        brief: topic.brief,
        briefError: "",
        style: "auto",
        source: topic.id,
        topicId: topic.topicId,
      });
      this.save();
      wx.pageScrollTo({ scrollTop: 0, duration: 0 });
    });
  },
  save() {
    const { kind, brief, style, source, asset, assetMode, assetConfirmed } =
      this.data;
    wx.setStorageSync("trupic.draft", {
      kind,
      brief,
      style,
      source,
      // Keep the known owner when saving before this page has learned the active workspace.
      workspace: this.workspace || this.draftWorkspace || undefined,
      topicId: this.data.topicId,
      asset,
      assetMode,
      assetConfirmed,
      identityRegion: this.data.identityRegion,
      visualDetail: this.data.visualDetail,
    });
  },
  input(e) {
    this.setData({
      brief: e.detail.value,
      ...(e.detail.value.trim().length >= 2 ? { briefError: "" } : {}),
      ...(e.detail.value.trim() ? {} : { topicId: "", source: "一句话创作" }),
    });
    this.save();
  },
  blurBrief() {
    this.setData({ focusBrief: false });
  },
  changeKind(e) {
    const kind = e.currentTarget.dataset.kind;
    this.setData({ kind, format: this.formats[kind] || defaults.poster });
    this.save();
  },
  settings() {
    const f = this.data.format;
    this.setData({
      sheet: "format",
      ratioIndex: ratios.indexOf(f.ratio),
      resolutionIndex: resolutions.indexOf(f.resolution),
      dpiIndex: dpis.indexOf(f.dpi),
    });
  },
  close() {
    this.setData({ sheet: "" });
  },
  pickRatio(e) {
    this.selectFormat({
      currentTarget: { dataset: { key: "ratio" } },
      detail: { value: Number(e.currentTarget.dataset.index) },
    });
  },
  selectFormat(e) {
    const key = e.currentTarget.dataset.key;
    const choices = { ratio: ratios, resolution: resolutions, dpi: dpis };
    const format = {
      ...this.data.format,
      [key]: choices[key][Number(e.detail.value)],
    };
    this.formats[this.data.kind] = format;
    wx.setStorageSync("trupic.formats", this.formats);
    this.setData({ format, [key + "Index"]: Number(e.detail.value) });
  },
  gallery() {
    wx.switchTab({ url: "/pages/inspiration/inspiration" });
  },
  sample(e) {
    getApp().globalData.showSample = e.currentTarget.dataset.id;
    this.gallery();
  },
  addPhoto() {
    wx.chooseMedia({
      count: 1,
      mediaType: ["image"],
      sourceType: ["album", "camera"],
      success: async (r) => {
        this.setData({ busy: true, uploading: true });
        try {
          const asset = await api.upload(r.tempFiles[0].tempFilePath);
          this.setData({
            asset,
            identityRegion: null,
            visualDetail: null,
            regionStyle: "",
            marking: false,
            assetMode: "processed",
            assetConfirmed: false,
            assetImage: "",
            sheet: "asset",
          });
          this.save();
          await this.showPhoto();
        } catch (e) {
          api.message(e);
        } finally {
          this.setData({ busy: false, uploading: false });
        }
      },
    });
  },
  async showPhoto() {
    const request = (this.photoRequest || 0) + 1;
    this.photoRequest = request;
    this.setData({
      photoError: "",
      sheet: "asset",
      assetImage: "",
      marking: false,
      firstCorner: null,
    });
    const { asset, assetMode } = this.data;
    try {
      const src = await api.download(
        assetMode === "original" ? asset.original : asset.url,
      );
      if (
        this.photoRequest === request &&
        this.data.asset &&
        this.data.asset.id === asset.id &&
        this.data.assetMode === assetMode
      )
        this.setData({ assetImage: src });
    } catch (e) {
      if (this.photoRequest === request && this.data.asset?.id === asset.id)
        this.setData({ photoError: e.message || "未能加载商品图。" });
    }
  },
  togglePhoto(e) {
    this.setData({
      assetMode: e.detail.value ? "original" : "processed",
      assetConfirmed: false,
    });
    this.save();
    this.showPhoto();
  },
  regionStyle(area) {
    return area
      ? "left:" +
          area[0] * 100 +
          "%;top:" +
          area[1] * 100 +
          "%;width:" +
          (area[2] - area[0]) * 100 +
          "%;height:" +
          (area[3] - area[1]) * 100 +
          "%"
      : "";
  },
  async startMark(e) {
    const asset = this.data.asset;
    const detail = e?.currentTarget?.dataset?.target === "detail";
    try {
      const image = await api.download(asset.original);
      if (asset.id !== this.data.asset?.id || this.data.sheet !== "asset")
        return;
      this.setData({ marking: true, markingDetail: detail, regionImage: image, firstCorner: null,
        regionStyle: this.regionStyle(detail ? this.data.visualDetail?.region : this.data.identityRegion) });
    } catch (e) {
      api.message(e);
    }
  },
  markPoint(e) {
    const { clientX, clientY } = e.changedTouches[0];
    this.createSelectorQuery()
      .select(".region-image")
      .boundingClientRect((rect) => {
        if (!rect || !this.data.marking) return;
        const clamp = (n) => Math.max(0, Math.min(1, n));
        const x = clamp((clientX - rect.left) / rect.width),
          y = clamp((clientY - rect.top) / rect.height);
        const first = this.data.firstCorner;
        if (!first) return this.setData({ firstCorner: [x, y] });
        const area = [
          Math.min(first[0], x),
          Math.min(first[1], y),
          Math.max(first[0], x),
          Math.max(first[1], y),
        ];
        if (area[0] === area[2] || area[1] === area[3]) return;
        this.setData({
          ...(this.data.markingDetail
            ? { visualDetail: { region: area, label: this.data.visualDetail?.label || "" } }
            : { identityRegion: area }),
          regionStyle: this.regionStyle(area),
          firstCorner: null,
          assetConfirmed: false,
        });
        this.save();
      })
      .exec();
  },
  detailLabel(e) {
    this.setData({ visualDetail: { ...this.data.visualDetail, label: e.detail.value }, assetConfirmed: false });
    this.save();
  },
  clearRegion(e) {
    const detail = e?.currentTarget?.dataset?.target === "detail";
    this.setData({
      ...(detail ? { visualDetail: null } : { identityRegion: null }),
      firstCorner: null,
      regionStyle: "",
      marking: false,
      assetConfirmed: false,
    });
    this.save();
  },
  acceptPhoto() {
    if (!this.data.assetImage || this.data.firstCorner) return;
    if (this.data.kind === "video" && this.data.visualDetail && !this.data.visualDetail.label.trim()) {
      return wx.showToast({ title: "请填写框内可见的细节", icon: "none" });
    }
    this.setData({ assetConfirmed: true, sheet: "" });
    this.save();
  },
  removePhoto() {
    this.setData({
      asset: null,
      identityRegion: null,
      visualDetail: null,
      regionStyle: "",
      marking: false,
      assetImage: "",
      assetConfirmed: false,
      sheet: "",
    });
    this.save();
  },
  async preview() {
    if (this.data.busy) return;
    const {
      brief,
      kind,
      asset,
      assetConfirmed,
      assetMode,
      source,
      format,
      style,
    } = this.data;
    if (brief.trim().length < 2) {
      this.setData({ briefError: "请至少写两个字，描述想推广的商品或活动。", focusBrief: true });
      return;
    }
    if (asset && kind !== "copy" && !assetConfirmed) {
      this.showPhoto();
      return;
    }
    this.setData({ busy: true });
    try {
      const result = await api.request("preview", "POST", {
        brief,
        kind,
        asset: asset ? asset.id : "",
        assetMode,
        assetConfirmed,
        ratio: ratioKeys[ratios.indexOf(format.ratio)],
        resolution: format.resolution,
        dpi: format.dpi,
        posterStyle: style,
        identityRegion: this.data.identityRegion,
        visualDetail: kind === "video" ? this.data.visualDetail : null,
        source,
        topicId: this.data.topicId,
      });
      getApp().globalData.preview = result;
      wx.navigateTo({ url: "/pages/confirm/confirm" });
    } catch (e) {
      if (asset && /标出要保真|所选标识|原图标识区域/.test(e.message)) {
        await this.showPhoto();
        await this.startMark();
      }
      api.message(e);
    } finally {
      this.setData({ busy: false });
    }
  },
});
