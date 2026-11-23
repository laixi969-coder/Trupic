const api = require("../../lib/api");
const labels = { poster: "营销海报", video: "宣传短片", copy: "推广文案" };
Page({
  data: { preview: null, options: [], copyChoice: "", busy: false, error: "" },
  onLoad() {
    const preview = getApp().globalData.preview;
    if (!preview) {
      this.setData({ error: "方案已失效，请返回首页重新预览。" });
      return;
    }
    if (!preview.requestKey)
      preview.requestKey =
        "wx-" + Date.now() + "-" + Math.random().toString(36).slice(2);
    this.setData({ preview, label: labels[preview.kind] });
  },
  copyPosterPrompt() {
    const chosen = this.data.options.find(o => o.token === this.data.copyChoice);
    wx.setClipboardData({ data: chosen?.fullPosterPrompt || this.data.preview.fullPosterPrompt });
  },
  async loadOptions() {
    if (this.data.busy) return;
    this.setData({ busy: true, error: "" });
    try {
      const result = await api.request("copy-options", "POST", { quote: this.data.preview.quote, previousTitles: this.data.options.map(o => o.title) });
      this.setData({ options: result.options, copyChoice: "" });
    } catch (e) {
      this.setData({ error: e.message });
    } finally {
      this.setData({ busy: false });
    }
  },
  chooseCopy(e) {
    this.setData({ copyChoice: e.detail.value });
  },
  async submit() {
    const p = this.data.preview;
    if (!p || this.data.busy || (p.requiresCopyChoice && !this.data.copyChoice)) return;
    this.setData({ busy: true, error: "" });
    try {
      const j = await api.request("jobs", "POST", {
        quote: p.quote,
        copyChoice: this.data.copyChoice,
        confirmed: true,
        confirmedCost: p.cost,
        requestKey: p.requestKey,
      });
      wx.redirectTo({ url: "/pages/result/result?job=" + j.id });
    } catch (e) {
      this.setData({ error: e.message });
    } finally {
      this.setData({ busy: false });
    }
  },
  home() {
    wx.switchTab({ url: "/pages/home/home" });
  },
});
