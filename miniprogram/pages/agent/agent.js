const api = require("../../lib/api");
const key = () => Date.now().toString(36) + Math.random().toString(36).slice(2);
const labels = {
  planning: "正在规划",
  waiting_input: "需要补充",
  waiting_copy: "请选择文案",
  waiting_script: "准备脚本",
  quoted: "等待确认",
  queued: "排队中",
  running: "正在制作",
  reviewing: "正在审核",
  delivered: "已交付",
  failed: "制作未全部完成",
  cancelled: "已取消",
};
function turns(chat) {
  const cards = new Map(chat.tasks.map((t) => [t.id, t]));
  const last = {};
  chat.messages.forEach((m) => {
    if (m.task) last[m.task] = m.seq;
  });
  return chat.messages
    .filter((m) => !m.task || last[m.task] === m.seq)
    .map((m) => {
      const card = cards.get(m.task);
      return card
        ? {
            ...m,
            card: {
              ...card,
              stateText: labels[card.status],
              canCancel: [
                "planning",
                "waiting_input",
                "waiting_copy",
                "waiting_script",
                "quoted",
                "queued",
              ].includes(card.status),
            },
          }
        : m;
    });
}

Page({
  data: {
    text: "",
    chat: null,
    turns: [],
    history: [],
    showHistory: false,
    busy: false,
    error: "",
    asset: null,
  },
  onLoad() {
    this.workspace = "";
    this.serial = 0;
  },
  async onShow() {
    this.visible = true;
    await this.act(async () => {
      const state = await api.request("state");
      if (this.workspace !== state.workspace) {
        this.ref = null;
        this.workspace = state.workspace;
        this.setData({ chat: null, turns: [], asset: null, text: "" });
      }
      const home = await api.request("agent");
      this.setData({ history: home.conversations });
      const saved = wx.getStorageSync("trupic.agent." + this.workspace);
      const target =
        home.conversations.find((r) => r.id === saved) || home.conversations[0];
      if (target)
        this.display(
          await api.request(
            "agent/conversations/" + target.id + "/visit",
            "POST",
            {},
          ),
        );
    });
  },
  onHide() {
    this.visible = false;
    clearTimeout(this.timer);
    this.serial++;
  },
  onUnload() {
    this.onHide();
  },
  async act(fn) {
    if (this.data.busy) return;
    this.serial++;
    clearTimeout(this.timer);
    this.setData({ busy: true, error: "" });
    try {
      await fn();
    } catch (e) {
      this.setData({ error: e.message });
    } finally {
      this.setData({ busy: false });
      this.schedule();
    }
  },
  display(c) {
    this.setData({ chat: c, turns: turns(c) });
    wx.setStorageSync("trupic.agent." + this.workspace, c.id);
  },
  schedule() {
    clearTimeout(this.timer);
    if (!this.visible || !this.data.chat) return;
    const serial = this.serial,
      id = this.data.chat.id;
    this.timer = setTimeout(
      async () => {
        try {
          const c = await api.request("agent/conversations/" + id);
          if (this.visible && this.serial === serial) this.display(c);
        } catch (e) {
          if (this.visible && this.serial === serial)
            this.setData({ error: e.message });
        } finally {
          if (this.visible && this.serial === serial) this.schedule();
        }
      },
      this.data.chat.tasks.some((t) =>
        ["planning", "queued", "running", "reviewing"].includes(t.status),
      )
        ? 2000
        : 12000,
    );
  },
  input(e) {
    this.setData({ text: e.detail.value });
  },
  async create() {
    this.ref = null;
    const c = await api.request("agent/conversations", "POST", {});
    this.display(c);
    return c;
  },
  fresh() {
    return this.act(async () => {
      await this.create();
      this.setData({ text: "", asset: null, showHistory: false });
    });
  },
  history() {
    return this.act(async () => {
      this.setData({
        history: (await api.request("agent")).conversations,
        showHistory: !this.data.showHistory,
      });
    });
  },
  open(e) {
    this.ref = null;
    return this.act(async () => {
      this.display(
        await api.request(
          "agent/conversations/" + e.currentTarget.dataset.id + "/visit",
          "POST",
          {},
        ),
      );
      this.setData({ showHistory: false, text: "", asset: null });
    });
  },
  async sendText(text, extra = {}) {
    if (!text.trim()) return;
    return this.act(async () => {
      const c = this.data.chat || (await this.create());
      const storage = "trupic.agent.message." + c.id;
      const payload = {
        text,
        options: this.data.asset
          ? { asset: this.data.asset.id, assetMode: "original" }
          : {},
        ...extra,
      };
      if (!extra.action && c.tasks.length) {
        const current = c.tasks[c.tasks.length - 1];
        payload.task = current.id;
        payload.revision = current.revision;
      }
      const signature = JSON.stringify(payload);
      let last = wx.getStorageSync(storage);
      if (last?.signature !== signature) {
        last = { signature, key: key() };
        wx.setStorageSync(storage, last);
      }
      this.display(
        await api.request("agent/conversations/" + c.id + "/messages", "POST", {
          ...payload,
          requestKey: last.key,
        }),
      );
      wx.setStorageSync(storage, null);
      this.ref = null;
      this.setData({ text: "", asset: null });
    });
  },
  send() {
    return this.sendText(
      this.data.text,
      this.ref ? { action: "new", workRef: this.ref } : {},
    );
  },
  topic(e) {
    const r = e.currentTarget.dataset.item;
    return this.sendText(r.brief, {
      action: "new",
      options: { topicId: r.topicId },
    });
  },
  switchTask(e) {
    const d = e.currentTarget.dataset;
    return this.sendText(d.item.text, {
      action: d.action,
      options: d.item.options,
    });
  },
  choose(e) {
    const d = e.currentTarget.dataset;
    return this.sendText("选第" + (d.index + 1) + "组", {
      action: "select",
      task: d.card.id,
      revision: d.card.revision,
      index: d.index,
    });
  },
  pickWork(e) {
    const { work, question } = e.currentTarget.dataset;
    if (question.needsInstruction) {
      this.ref = work;
      this.setData({ text: "照这个再做，" });
      return;
    }
    return this.sendText(question.instruction, {
      action: "new",
      workRef: work,
    });
  },
  stage(e) {
    const { card, action } = e.currentTarget.dataset;
    return this.act(async () => {
      await api.request("agent/tasks/" + card.id + "/" + action, "POST", {
        revision: card.revision,
        quoteId: card.quoteId,
        confirmedCost: card.cost,
        approvalType: "production",
        requestKey: "approve-" + card.quoteId,
      });
      this.display(
        await api.request("agent/conversations/" + this.data.chat.id),
      );
    });
  },
  requote(e) {
    const t = e.currentTarget.dataset.card;
    return this.sendText("刷新报价", {
      action: "refresh",
      task: t.id,
      revision: t.revision,
    });
  },
  addPhoto() {
    wx.chooseMedia({
      count: 1,
      mediaType: ["image"],
      success: (r) =>
        this.act(async () => {
          this.setData({
            asset: await api.upload(r.tempFiles[0].tempFilePath),
          });
        }),
    });
  },
  result(e) {
    wx.navigateTo({
      url: "/pages/result/result?id=" + e.currentTarget.dataset.id,
    });
  },
  copy(e) {
    wx.setClipboardData({ data: e.currentTarget.dataset.text });
  },
});
