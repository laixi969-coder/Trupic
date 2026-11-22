const api = require("../../lib/api");
Page({
  data: {
    state: "loading",
    error: "",
    work: null,
    version: null,
    media: "",
    busy: false,
  },
  onLoad(options) {
    this.job = options.job;
    this.id = options.id;
    this.epoch = 0;
  },
  onShow() {
    this.refresh();
  },
  onHide() {
    this.stop();
  },
  onUnload() {
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
      }
      const work = await api.request("works/" + this.id);
      const version = work.versions.find((v) => v.n === work.current);
      if (epoch !== this.epoch) return;
      this.setData({ state: "complete", error: "", work, version, media: "" });
      if (work.kind !== "copy") {
        const media = await api.download(version.video || version.poster);
        if (epoch === this.epoch) this.setData({ media });
      }
    } catch (e) {
      if (epoch === this.epoch)
        this.setData({ state: "error", error: e.message });
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
