const api = require("../../lib/api");
Page({
  data: {
    state: "loading",
    error: "",
    work: null,
    version: null,
    media: "",
    versionLabels: [],
    versionIndex: 0,
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
          this.setData({ state: j.state, error: j.error || "" });
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
      version,
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
  async revise(e) {
    if (this.data.busy || this.job) return;
    const action = e.currentTarget.dataset.action;
    const base = this.data.version.n;
    const operation = base + "-" + action;
    if (this.operation !== operation) {
      this.operation = operation;
      this.requestKey =
        "wx-" + Date.now() + "-" + Math.random().toString(36).slice(2);
    }
    this.setData({ busy: true });
    try {
      const q = await api.request("works/" + this.id + "/revision-quote", "POST", {action, base});
      const consent = await new Promise((resolve, reject) => wx.showModal({ title:"确认修改", content:"本次共 " + q.cost + " 积分，原作品会保留。", success:resolve, fail:reject }));
      if (!consent.confirm) return;
      const job = await api.request("works/" + this.id + "/revise", "POST", {
        quote:q.quote, confirmed:true, confirmedCost:q.cost,
        action,
        base,
        requestKey: this.requestKey,
      });
      this.job = job.id;
      this.operation = null;
      this.setData({ state: "queued" });
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
      data: [v.title, v.body, v.cta].filter(Boolean).join("\n\n"),
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
      const method =
        this.data.work.kind === "video"
          ? "saveVideoToPhotosAlbum"
          : "saveImageToPhotosAlbum";
      await new Promise((resolve, reject) =>
        wx[method]({
          filePath: path,
          success: resolve,
          fail: () => reject(new Error("保存失败，请检查相册权限后重试")),
        }),
      );
      wx.showToast({ title: "已保存到相册" });
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
