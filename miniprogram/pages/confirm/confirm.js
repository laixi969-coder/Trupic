const api = require("../../lib/api");
const labels = { poster: "营销海报", video: "宣传短片", copy: "推广文案" };
Page({
  data: { preview: null, busy: false, error: "" },
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
    wx.setClipboardData({ data: this.data.preview.fullPosterPrompt });
  },
  async submit() {
    const p = this.data.preview;
    if (!p || this.data.busy) return;
    this.setData({ busy: true, error: "" });
    try {
      const j = await api.request("jobs", "POST", {
        quote: p.quote,
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
