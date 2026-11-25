const api = require("../../lib/api");
const labels = { poster: "营销海报", copy: "推广文案", video: "宣传短片" };
// The same list as the web profile; several can be chosen and custom names added.
const industries = [
  "茶饮咖啡",
  "餐饮火锅",
  "烘焙甜品",
  "休闲娱乐",
  "美容护理",
  "诊所",
  "健身运动",
  "零售服务",
  "生活用品",
  "其他",
];
const fields = [
  { key: "name", label: "商家名称" },
  { key: "product", label: "主营商品" },
  { key: "audience", label: "目标顾客" },
  { key: "city", label: "经营城市" },
  { key: "tone", label: "品牌语气" },
];
const emptyForm = () => ({ industryTags: [], customIndustry: "" });
const industryRows = (tags) =>
  [...new Set([...industries, ...tags])].map((name) => ({ name, on: tags.includes(name) }));

Page({
  data: {
    works: [],
    jobs: [],
    runs: [],
    profile: {},
    profileFields: fields,
    credits: 0,
    ledger: [],
    showLedger: false,
    trialNote: "",
    account: "",
    loaded: false,
    error: "",
    edit: false,
    saving: false,
    // History is deleted at once and restored from a short-lived undo notice.
    managing: false,
    trash: null,
    login: "",
    password: "",
    mode: "register",
  },
  onShow() {
    return this.load();
  },
  onHide() {
    clearTimeout(this.trashTimer);
  },
  async load() {
    try {
      const [state, runs] = await Promise.all([
        api.request("state"),
        api.request("creations").catch(() => []),
      ]);
      this.setData({
        works: state.works.map((w) => ({ ...w, label: labels[w.kind] })),
        runs: runs.map((run) => ({
          ...run,
          done: run.items.filter((item) => item.state === "complete").length,
        })),
        jobs: state.jobs,
        profile: state.profile,
        credits: state.credits,
        ledger: state.ledger,
        trialNote: state.trialNote || "",
        account: state.login || "",
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
  openRun(e) {
    wx.navigateTo({ url: "/pages/run/run?run=" + e.currentTarget.dataset.id });
  },
  create() {
    wx.navigateTo({ url: "/pages/quick/quick" });
  },
  shop() {
    wx.navigateTo({ url: "/pages/shop/shop" });
  },
  toggleLedger() {
    this.setData({ showLedger: !this.data.showLedger });
  },
  edit() {
    const tags = this.data.profile.industryTags || (this.data.profile.industry || "").split("、").filter(Boolean);
    this.setData({
      edit: true,
      form: { ...this.data.profile, ...emptyForm(), industryTags: tags },
      industryRows: industryRows(tags),
    });
  },
  close() {
    if (this.data.saving) return;
    const changed = Object.keys(this.data.form).some(
      (key) => JSON.stringify(this.data.form[key]) !== JSON.stringify(this.data.profile[key] ?? (key === "industryTags" ? [] : "")),
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
    const { key } = e.currentTarget.dataset;
    this.setData({ form: { ...this.data.form, [key]: e.detail.value } });
  },
  toggleIndustry(e) {
    const name = e.currentTarget.dataset.name;
    const tags = this.data.form.industryTags;
    const next = tags.includes(name) ? tags.filter((t) => t !== name) : tags.length < 10 ? [...tags, name] : tags;
    this.setData({ form: { ...this.data.form, industryTags: next }, industryRows: industryRows(next) });
  },
  addIndustry() {
    const name = (this.data.form.customIndustry || "").trim().slice(0, 24);
    const tags = this.data.form.industryTags;
    if (!name || tags.includes(name) || tags.length >= 10) return;
    this.setData({
      form: { ...this.data.form, industryTags: [...tags, name], customIndustry: "" },
      industryRows: industryRows([...tags, name]),
    });
  },
  async save() {
    if (this.data.saving) return;
    this.setData({ saving: true });
    try {
      const { industryTags, customIndustry, ...rest } = this.data.form;
      await api.request("profile", "POST", { ...rest, industryTags, industry: industryTags.join("、") });
      this.setData({ edit: false });
      await this.load();
    } catch (e) {
      api.message(e);
    } finally {
      this.setData({ saving: false });
    }
  },
  manage() {
    if (this.data.trash) return;
    this.setData({ managing: !this.data.managing, selected: [] });
  },
  toggle(e) {
    const id = e.currentTarget.dataset.id;
    const selected = this.data.selected.includes(id)
      ? this.data.selected.filter((x) => x !== id)
      : [...this.data.selected, id];
    this.setData({ selected, works: this.data.works.map((w) => ({ ...w, checked: selected.includes(w.id) })) });
  },
  selectAll() {
    const all = this.data.selected.length === this.data.works.length;
    this.setData({ selected: all ? [] : this.data.works.map((w) => w.id), works: this.data.works.map((w) => ({ ...w, checked: !all })) });
  },
  async trash(body) {
    try {
      const result = await api.request("works/trash", "POST", body);
      this.setData({ selected: [], managing: false, trash: result });
      await this.load();
      clearTimeout(this.trashTimer);
      this.trashTimer = setTimeout(() => this.setData({ trash: null }), 8000);
    } catch (e) {
      api.message(e);
    }
  },
  removeSelected() {
    if (this.data.selected.length) return this.trash({ ids: this.data.selected });
  },
  removeAll() {
    if (this.data.works.length) return this.trash({ all: true });
  },
  async undo() {
    clearTimeout(this.trashTimer);
    const batch = this.data.trash?.batch;
    this.setData({ trash: null });
    if (!batch) return;
    try {
      await api.request("works/trash/" + batch + "/undo", "POST", {});
      await this.load();
      wx.showToast({ title: "已恢复", icon: "none" });
    } catch (e) {
      api.message(e);
    }
  },
  mode(e) {
    this.setData({ mode: e.currentTarget.dataset.mode, error: "" });
  },
  async bind() {
    if (this.data.saving) return;
    this.setData({ saving: true, error: "" });
    try {
      await api.request("account/" + this.data.mode, "POST", { login: this.data.login, password: this.data.password });
      // Another account must not inherit the drafts of the previous one.
      for (const key of ["trupic.draft", "trupic.quick"]) wx.setStorageSync(key, null);
      getApp().globalData.preview = null;
      getApp().globalData.quickPlan = null;
      this.setData({ password: "" });
      await this.load();
    } catch (e) {
      this.setData({ error: e.message });
    } finally {
      this.setData({ saving: false });
    }
  },
  async logout() {
    if (this.data.saving) return;
    this.setData({ saving: true });
    try {
      await api.request("account/logout", "POST", {});
      for (const key of ["trupic.draft", "trupic.quick"]) wx.setStorageSync(key, null);
      getApp().globalData.preview = null;
      getApp().globalData.quickPlan = null;
      await this.load();
    } catch (e) {
      this.setData({ error: e.message });
    } finally {
      this.setData({ saving: false });
    }
  },
});
