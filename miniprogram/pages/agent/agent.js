const api = require("../../lib/api");
const audio = require("../../lib/agent-speech");
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
              deliveryLabel: (card.deliveries || []).join("、") ||
                ({ copy: "推广文案", poster: "营销海报", video: "宣传短片" })[card.kind],
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
  ...audio.methods,
  data: {
    ...audio.data,
    text: "",
    chat: null,
    turns: [],
    history: [],
    showHistory: false,
    busy: false,
    error: "",
    asset: null,
    assetPhoto: "",
    focusedTask: "",
    workspaceReady: false,
  },
  onLoad(query = {}) {
    this.workspace = "";
    this.serial = 0;
    this.entryRoute = query;
    this.emptyNew = query.mode === "new" || query.mode === "call";
    if (query.mode === "new" || query.mode === "call") {
      this.entryDraft = getApp().globalData.agentEntry;
      getApp().globalData.agentEntry = null;
    }
  },
  async onShow() {
    this.visible = true;
    this.setData({ workspaceReady: false });
    const route = this.entryRoute || {};
    let scrollTask;
    const ready = await this.act(async (valid) => {
      const home = await api.request("agent");
      if (!valid()) return;
      if (this.workspace !== home.workspace) {
        this.ref = null;
        this.workspace = home.workspace;
        this.setData({ chat: null, turns: [], asset: null, assetPhoto: "", text: "", focusedTask: "", showHistory: false });
      }
      this.setData({ history: home.conversations, showHistory: route.mode === "history" });
      const saved = wx.getStorageSync("trupic.agent." + this.workspace);
      const preferred = route.conversation || this.data.chat?.id || saved;
      const target = home.conversations.find((r) => r.id === preferred)?.id ||
        (!route.conversation && home.conversations[0]?.id);
      if (route.conversation && !target) throw new Error("这段对话已归档或不属于当前商家。");
      if (target && !this.emptyNew) {
        const chat = await api.request("agent/conversations/" + target + "/visit", "POST", {});
        if (!valid()) return;
        const focus = chat.tasks.find((task) => task.id === route.task);
        this.setData({ focusedTask: focus?.id || this.data.focusedTask });
        this.display(chat);
        scrollTask = focus?.id;
      }
      this.setData({ workspaceReady: true }, () => {
        if (scrollTask && this.visible && wx.pageScrollTo)
          wx.pageScrollTo({ selector: "#task-" + scrollTask, duration: 250 });
      });
      return true;
    });
    if (!ready || !this.visible) return;
    this.entryRoute = null;
    const entry = this.entryDraft;
    this.entryDraft = null;
    if (entry && entry.workspace === this.workspace) {
      this.setData({ text: entry.text || "", asset: entry.asset || null, assetPhoto: entry.photo || "" });
      if (entry.send && this.data.text.trim()) await this.send();
    }
    if (route.mode === "call" && this.visible && (!entry || entry.workspace === this.workspace))
      this.toggleCall();
  },
  onHide() {
    this.visible = false;
    clearTimeout(this.timer);
    this.serial++;
    this.switchAudioOff();
    this.setData({ busy: false });
  },
  onUnload() {
    this.onHide();
  },
  async act(fn) {
    if (this.data.busy) return;
    const serial = ++this.serial;
    const valid = () => this.visible && this.serial === serial;
    clearTimeout(this.timer);
    this.setData({ busy: true, error: "" });
    try {
      return await fn(valid);
    } catch (e) {
      if (valid()) this.setData({ error: e.message });
    } finally {
      if (valid()) {
        this.setData({ busy: false });
        this.schedule();
      }
    }
  },
  display(c) {
    this.emptyNew = false;
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
  async create(valid) {
    this.ref = null;
    const c = await api.request("agent/conversations", "POST", {});
    if (valid()) this.display(c);
    return c;
  },
  fresh() {
    this.switchAudioOff();
    return this.act(async (valid) => {
      await this.create(valid);
      if (valid()) this.setData({ text: "", asset: null, assetPhoto: "", focusedTask: "", showHistory: false });
    });
  },
  history() {
    this.switchAudioOff();
    return this.act(async (valid) => {
      const home = await api.request("agent");
      if (!valid()) return;
      this.setData({
        history: home.conversations,
        showHistory: !this.data.showHistory,
      });
    });
  },
  open(e) {
    this.ref = null;
    this.switchAudioOff();
    return this.act(async (valid) => {
      const chat = await api.request("agent/conversations/" + e.currentTarget.dataset.id + "/visit", "POST", {});
      if (!valid()) return;
      this.display(chat);
      this.setData({ showHistory: false, text: "", asset: null, assetPhoto: "", focusedTask: "" });
    });
  },
  async sendText(text, extra = {}, { preserveDraft = false } = {}) {
    if (!text.trim()) return;
    return this.act(async (valid) => {
      const c = this.data.chat || (await this.create(valid));
      if (!valid()) return;
      const storage = "trupic.agent.message." + c.id;
      const payload = {
        text,
        options: this.data.asset
          ? { asset: this.data.asset.id, assetMode: "original" }
          : {},
        ...extra,
      };
      if (!extra.action && c.tasks.length) {
        const current = c.tasks.find((t) => t.id === this.data.focusedTask) || c.tasks[c.tasks.length - 1];
        payload.task = current.id;
        payload.revision = current.revision;
      }
      const signature = JSON.stringify(payload);
      let last = wx.getStorageSync(storage);
      if (last?.signature !== signature) {
        last = { signature, key: key() };
        wx.setStorageSync(storage, last);
      }
      const reply = await api.request("agent/conversations/" + c.id + "/messages", "POST", {
          ...payload,
          requestKey: last.key,
        });
      if (!valid()) return;
      this.display(reply);
      wx.setStorageSync(storage, null);
      this.ref = null;
      const newest = reply.tasks.find((task) => !c.tasks.some((old) => old.id === task.id));
      this.setData({ text: preserveDraft ? this.data.text : "", asset: null, assetPhoto: "",
        focusedTask: newest?.id || (reply.id === c.id ? this.data.focusedTask : "") });
      return reply;
    });
  },
  send() {
    this.switchAudioOff();
    return this.sendText(
      this.data.text,
      this.ref ? { action: "new", workRef: this.ref } : {},
    );
  },
  async loadSpokenChoices(cid, card, active) {
    await this.act(async (valid) => {
      await api.request("agent/tasks/" + card.id + "/options", "POST", { revision: card.revision });
      if (!active() || !valid()) return;
      const chat = await api.request("agent/conversations/" + cid);
      if (active() && valid()) this.display(chat);
    });
    if (active() && this.data.error) throw new Error(this.data.error);
  },
  topic(e) {
    this.switchAudioOff();
    const r = e.currentTarget.dataset.item;
    return this.sendText(r.brief, {
      action: "new",
      options: { topicId: r.topicId },
    });
  },
  switchTask(e) {
    this.switchAudioOff();
    const d = e.currentTarget.dataset;
    return this.sendText(d.item.text, {
      action: d.action,
      options: d.item.options,
    });
  },
  choose(e) {
    this.switchAudioOff();
    const d = e.currentTarget.dataset;
    return this.sendText("选第" + (d.index + 1) + "组", {
      action: "select",
      task: d.card.id,
      revision: d.card.revision,
      index: d.index,
    });
  },
  pickWork(e) {
    this.switchAudioOff();
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
    this.switchAudioOff();
    return this.act(async (valid) => {
      await api.request("agent/tasks/" + card.id + "/" + action, "POST", {
        revision: card.revision,
        quoteId: card.quoteId,
        confirmedCost: card.cost,
        approvalType: "production",
        requestKey: "approve-" + card.quoteId,
      });
      if (!valid()) return;
      const chat = await api.request("agent/conversations/" + this.data.chat.id);
      if (valid()) this.display(chat);
    });
  },
  requote(e) {
    this.switchAudioOff();
    const t = e.currentTarget.dataset.card;
    return this.sendText("刷新报价", {
      action: "refresh",
      task: t.id,
      revision: t.revision,
    });
  },
  addPhoto() {
    this.switchAudioOff();
    wx.chooseMedia({
      count: 1,
      mediaType: ["image"],
      success: (r) =>
        this.act(async (valid) => {
          const assetPhoto = r.tempFiles[0].tempFilePath;
          const asset = await api.upload(assetPhoto);
          if (valid()) this.setData({ asset, assetPhoto });
        }),
    });
  },
  removePhoto() { this.setData({ asset: null, assetPhoto: "" }); },
  result(e) {
    wx.navigateTo({
      url: "/pages/result/result?id=" + e.currentTarget.dataset.id,
    });
  },
  copy(e) {
    wx.setClipboardData({ data: e.currentTarget.dataset.text });
  },
});
