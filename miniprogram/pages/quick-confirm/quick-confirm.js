// Confirm the priced plan, choose reviewed poster copy when a poster is included, then start.
const api = require("../../lib/api");

Page({
  data: { plan: null, cost: 0, options: [], choice: "", busy: false, error: "" },
  onLoad() {
    const quick = getApp().globalData.quickPlan;
    this.setData(quick ? { plan: quick.plan, cost: quick.plan.cost, delivery: quick.plan.deliveries.map((d) => d.label).join("、") } : { error: "方案已失效，请返回重新检查需求。" });
  },
  async loadOptions() {
    if (this.data.busy) return;
    this.setData({ busy: true, error: "" });
    try {
      const result = await api.request("copy-options", "POST", {
        quote: this.data.plan.quote,
        previousTitles: this.data.options.map((o) => o.title),
      });
      this.setData({ options: result.options, choice: "" });
    } catch (e) {
      this.setData({ error: e.message });
    } finally {
      this.setData({ busy: false });
    }
  },
  choose(e) {
    this.setData({ choice: e.detail.value });
  },
  async submit() {
    const { plan, choice } = this.data;
    if (!plan || this.data.busy || (plan.requiresCopyChoice && !choice)) return;
    this.setData({ busy: true, error: "" });
    try {
      const run = await api.request("creations", "POST", {
        quote: plan.quote,
        copyChoice: plan.requiresCopyChoice ? choice : "",
        confirmedCost: plan.cost,
        requestKey: getApp().globalData.quickPlan.requestKey,
      });
      getApp().globalData.quickPlan = null;
      wx.redirectTo({ url: "/pages/run/run?run=" + run.id });
    } catch (e) {
      this.setData({ error: e.message });
    } finally {
      this.setData({ busy: false });
    }
  },
  back() {
    wx.navigateBack();
  },
});
