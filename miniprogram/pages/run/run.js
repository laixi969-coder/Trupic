// Progress and deliveries of one one-tap creation; each item recovers on its own.
const api = require("../../lib/api");
const { saveToAlbum } = require("../../lib/album");

const status = { queued: "排队中", running: "制作中", complete: "已完成", failed: "生成失败" };

Page({
  data: { run: null, items: [], error: "", busy: "", again: false },
  onLoad(options) {
    this.id = options.run;
    this.media = {};
  },
  onShow() {
    this.visible = true;
    return this.refresh();
  },
  onHide() {
    this.visible = false;
    clearTimeout(this.timer);
  },
  onUnload() {
    this.visible = false;
    clearTimeout(this.timer);
  },
  async refresh() {
    clearTimeout(this.timer);
    try {
      const run = await api.request("creations/" + this.id);
      if (this.visible === false) return;
      const items = run.items.map((item) => ({ ...item, statusText: status[item.state] || item.state }));
      const fresh = await Promise.all(
        items.filter((i) => i.preview || i.video).map(async (item) => {
          if (!this.media[item.job]) this.media[item.job] = await api.download(item.video || item.preview).catch(() => "");
          return item.job;
        }),
      );
      for (const job of fresh) if (this.media[job]) items.find((i) => i.job === job).media = this.media[job];
      this.setData({ run, items, error: "", again: false, done: items.filter((i) => i.state === "complete").length });
      if (run.active) this.timer = setTimeout(() => this.refresh(), 1500);
    } catch (e) {
      if (this.visible !== false) this.setData({ error: e.message });
    }
  },
  copy(e) {
    wx.setClipboardData({ data: e.currentTarget.dataset.text });
  },
  open(e) {
    wx.navigateTo({ url: "/pages/result/result?id=" + e.currentTarget.dataset.work });
  },
  async retry(e) {
    const job = e.currentTarget.dataset.job;
    if (this.data.busy) return;
    this.setData({ busy: job });
    try {
      await api.request("jobs/" + job + "/retry", "POST", {});
      await this.refresh();
    } catch (err) {
      api.message(err);
    } finally {
      this.setData({ busy: "" });
    }
  },
  async save(e) {
    const item = this.data.items.find((i) => i.job === e.currentTarget.dataset.job);
    if (this.data.busy || !item?.media) return;
    this.setData({ busy: item.job });
    try {
      wx.showToast({ title: await saveToAlbum(item.media, item.kind === "video"), icon: "none" });
    } catch (err) {
      api.message(err);
    } finally {
      this.setData({ busy: "" });
    }
  },
  // The same brief with a new plan, as on the web; the old run stays in history.
  redo() {
    this.setData({ again: true });
    wx.navigateBack();
  },
  mine() {
    wx.switchTab({ url: "/pages/mine/mine" });
  },
});
