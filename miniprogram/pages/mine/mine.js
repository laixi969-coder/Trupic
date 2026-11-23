const api = require("../../lib/api");
const labels = { poster: "营销海报", copy: "推广文案", video: "宣传短片" };
Page({
  data: {
    works: [],
    jobs: [],
    profile: {},
    profileFields: [
      { key: "name", label: "商家名称" },
      { key: "industry", label: "所属行业" },
      { key: "product", label: "主营商品" },
      { key: "audience", label: "目标顾客" },
      { key: "city", label: "经营城市" },
      { key: "tone", label: "品牌语气" },
    ],
    credits: 0,
    loaded: false,
    error: "",
    edit: false,
    saving: false,
  },
  onShow() {
    this.load();
  },
  async load() {
    try {
      const state = await api.request("state");
      this.setData({
        works: state.works.map((w) => ({ ...w, label: labels[w.kind] })),
        jobs: state.jobs,
        profile: state.profile,
        credits: state.credits,
        error: "",
        loaded: true,
      });
    } catch (e) {
      this.setData({ error: e.message });
    }
  },
  open(e) {
    wx.navigateTo({
      url:
        "/pages/result/result?" +
        e.currentTarget.dataset.key +
        "=" +
        e.currentTarget.dataset.id,
    });
  },
  create() {
    wx.switchTab({ url: "/pages/home/home" });
  },
  edit() {
    this.setData({ edit: true, form: { ...this.data.profile } });
  },
  close() {
    if (this.data.saving) return;
    const changed = Object.keys(this.data.form).some(
      key => (this.data.form[key] || "") !== (this.data.profile[key] || ""),
    );
    if (!changed) return this.setData({ edit: false });
    wx.showModal({
      title: "放弃未保存的修改？",
      cancelText: "继续编辑",
      confirmText: "放弃修改",
      success: ({ confirm }) => { if (confirm) this.setData({ edit: false }); },
    });
  },
  field(e) {
    this.setData({ ["form." + e.currentTarget.dataset.key]: e.detail.value });
  },
  async save() {
    if (this.data.saving) return;
    this.setData({ saving: true });
    try {
      await api.request("profile", "POST", {...this.data.form, industryTags:(this.data.form.industry || "").split(/[、，,]/).map(s=>s.trim()).filter(Boolean)});
      this.setData({ edit: false });
      await this.load();
    } catch (e) {
      api.message(e);
    } finally {
      this.setData({ saving: false });
    }
  },
});
