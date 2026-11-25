const api = require("../../lib/api");
const { saveToAlbum } = require("../../lib/album");
Page({
  data: {
    state: "loading",
    error: "",
    work: null,
    version: null,
    media: "",
    versionLabels: [],
    versionIndex: 0,
    copyMenu: null,
    busy: false,
  },
  onLoad(options) {
    this.job = options.job;
    this.id = options.id;
    this.epoch = 0;
  },
  onShow() {
    this.visible = true;
    return this.refresh();
  },
  onHide() {
    this.visible = false;
    this.stop();
  },
  onUnload() {
    this.visible = false;
    this.stop();
  },
  stop() {
    this.epoch++;
    clearTimeout(this.timer);
  },
  async refresh() {
    this.stop();
    const epoch = this.epoch;
    try {
      if (this.job) {
        const j = await api.request("jobs/" + this.job);
        if (epoch !== this.epoch) return;
        if (j.state !== "complete") {
          this.setData({ state: j.state, error: j.error || "", stage: j.stage || "" });
          if (j.state !== "failed")
            this.timer = setTimeout(() => this.refresh(), 1200);
          return;
        }
        this.id = j.work;
        this.job = null;
        this.selected = null;
      }
      const work = await api.request("works/" + this.id);
      if (epoch !== this.epoch) return;
      const index = work.versions.findIndex(
        (v) => v.n === (this.selected || work.current),
      );
      this.setData({
        work,
        versionLabels: work.versions.map(
          (v) => "版本 " + v.n + (v.n === work.current ? " · 当前" : ""),
        ),
      });
      await this.displayVersion(index < 0 ? 0 : index);
    } catch (e) {
      if (epoch === this.epoch)
        this.setData({ state: "error", error: e.message });
    }
  },
  async displayVersion(index) {
    this.stop();
    const epoch = this.epoch;
    const work = this.data.work;
    const version = work.versions[index];
    this.selected = version.n;
    this.setData({
      state: "complete",
      error: "",
      stage: "",
      version,
      isMoment: !!version.plan.moment,
      copyMenu: null,
      densePosterAdvice: work.kind === "poster" && version.n === 1 && version.brief.includes("满屏字"),
      versionIndex: index,
      media: "",
    });
    if (work.kind === "copy") return;
    try {
      const media = await api.download(version.video || version.poster);
      if (epoch === this.epoch) this.setData({ media });
    } catch (e) {
      if (epoch === this.epoch)
        this.setData({ state: "error", error: e.message });
    }
  },
  selectVersion(e) {
    return this.displayVersion(Number(e.detail.value));
  },
  async openCopies() {
    if (this.data.busy) return;
    const base = this.data.version.n;
    this.setData({ busy: true });
    try {
      const q = await api.request("works/" + this.id + "/revision-quote", "POST", { action: "moment-copy", base });
      if (this.data.version.n === base) this.setData({ copyMenu: { ...q, base } });
    } catch (e) {
      api.message(e);
    } finally {
      this.setData({ busy: false });
    }
  },
  closeCopies() {
    this.setData({ copyMenu: null });
  },
  async revise(e) {
    if (this.data.busy || this.job) return;
    const action = e.currentTarget.dataset.action;
    const base = this.data.version.n;
    const option = Number(e.currentTarget.dataset.option || 0);
    const menu = action === "moment-copy" ? this.data.copyMenu : null;
    if (action === "moment-copy" && menu?.base !== base) return;
    const operation = [base, action, option].join("-");
    if (this.operation !== operation) {
      this.operation = operation;
      this.requestKey =
        "wx-" + Date.now() + "-" + Math.random().toString(36).slice(2);
    }
    this.setData({ busy: true });
    try {
      const q = menu || await api.request("works/" + this.id + "/revision-quote", "POST", {action, base});
      if (!menu) {
        const consent = await new Promise((resolve, reject) => wx.showModal({
          title: "确认修改", content: (q.changes?.title ? "新标题：" + q.changes.title + "\n" : "") + "本次共 " + q.cost + " 积分，原作品会保留。", success: resolve, fail: reject,
        }));
        if (!consent.confirm) return;
      }
      const job = await api.request("works/" + this.id + "/revise", "POST", {
        quote:q.quote, confirmed:true, confirmedCost:q.cost,
        action, option,
        base,
        requestKey: this.requestKey,
      });
      this.job = job.id;
      this.operation = null;
      this.setData({ state: "queued", copyMenu: null });
      if (this.visible !== false) await this.refresh();
    } catch (e) {
      api.message(e);
    } finally {
      this.setData({ busy: false });
    }
  },
  async restore() {
    if (this.data.busy) return;
    this.setData({ busy: true });
    try {
      await api.request(
        "works/" + this.id + "/restore/" + this.data.version.n,
        "POST",
        {},
      );
      if (this.visible !== false) await this.refresh();
    } catch (e) {
      api.message(e);
    } finally {
      this.setData({ busy: false });
    }
  },
  async retry() {
    if (this.data.busy) return;
    this.setData({ busy: true });
    try {
      if (this.data.state === "failed")
        await api.request("jobs/" + this.job + "/retry", "POST", {});
      await this.refresh();
    } catch (e) {
      api.message(e);
    } finally {
      this.setData({ busy: false });
    }
  },
  copy() {
    const v = this.data.version;
    wx.setClipboardData({
      data: [this.data.isMoment ? "" : v.title, v.body, v.cta].filter(Boolean).join("\n\n"),
    });
  },
  copyPosterPrompt() {
    wx.setClipboardData({ data: this.data.version.fullPosterPrompt });
  },
  async save() {
    if (this.data.busy) return;
    this.setData({ busy: true });
    try {
      const path = await api.download(this.data.version.download);
      wx.showToast({ title: await saveToAlbum(path, this.data.work.kind === "video"), icon: "none" });
    } catch (e) {
      api.message(e);
    } finally {
      this.setData({ busy: false });
    }
  },
  mine() {
    wx.switchTab({ url: "/pages/mine/mine" });
  },
});
