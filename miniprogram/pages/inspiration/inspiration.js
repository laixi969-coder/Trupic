const { confirmBriefChange } = require("../../lib/draft");
const samples = require("../../lib/samples");
Page({
  data: {
    categories: ["全部", ...samples.map((s) => s.category)],
    category: "全部",
    samples,
    selected: null,
  },
  onShow() {
    const app = getApp();
    if (app.globalData.showSample) {
      this.setData({
        selected: samples.find((s) => s.id === app.globalData.showSample),
      });
      app.globalData.showSample = null;
    }
  },
  filter(e) {
    const category = e.currentTarget.dataset.cat;
    this.setData({
      category,
      samples:
        category === "全部"
          ? samples
          : samples.filter((s) => s.category === category),
    });
  },
  open(e) {
    this.setData({
      selected: samples.find((s) => s.id === e.currentTarget.dataset.id),
    });
  },
  close() {
    this.setData({ selected: null });
  },
  use() {
    const sample = this.data.selected;
    const draft = wx.getStorageSync("trupic.draft");
    confirmBriefChange(draft?.brief, sample.brief, () => {
      getApp().globalData.sample = sample;
      this.close();
      this.create();
    });
  },
  create() {
    wx.switchTab({ url: "/pages/home/home" });
  },
});
