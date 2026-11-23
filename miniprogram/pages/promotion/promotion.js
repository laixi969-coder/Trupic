const api = require("../../lib/api");

const stages = {
  pending: "待结算",
  settled: "已结算",
  reversed: "退款已冲回",
  recovery_due: "待追回",
  recovered: "已追回",
  payer_review: "代付待核对",
};

Page({
  data: {
    registered: false,
    mode: "register",
    login: "",
    password: "",
    offers: [],
    links: [],
    busy: false,
    error: "",
  },
  onLoad(query = {}) {
    this.source = { invite: query.invite || "", channel: query.channel || "" };
    this.setData({ invited: !!this.source.invite });
  },
  onShow() {
    return this.load();
  },
  async load() {
    try {
      const account = await api.request("state");
      if (account.login && this.source.invite) {
        await api.request("promotion/claim", "POST", {
          code: this.source.invite,
          channel: this.source.channel,
        });
        this.source = {};
      }
      const promotion = await api.request("promotion");
      const links = Object.entries(promotion.codes).map(([kind, code]) => ({
        label: kind === "agent" ? "渠道推广" : "商家邀请",
        query: "invite=" + code,
      }));
      if (promotion.channel)
        links.push({
          label: "商家与渠道联合推广",
          query:
            "invite=" +
            promotion.codes.merchant +
            "&channel=" +
            promotion.channel,
        });
      this.setData({
        registered: !!account.login,
        account: account.login || "",
        links,
        role: promotion.role || "",
        invites: promotion.invites || [],
        clients: promotion.clients,
        team: promotion.team || [],
        coupons: promotion.coupons || [],
        commissions: promotion.commissions.map((row) => ({
          ...row,
          money: (row.amount / 100).toFixed(2),
          stage: stages[row.status],
        })),
        error: "",
      });
    } catch (e) {
      this.setData({ error: e.message });
    }
  },
  field(e) {
    this.setData({ [e.currentTarget.dataset.key]: e.detail.value });
  },
  mode(e) {
    this.setData({ mode: e.currentTarget.dataset.mode, error: "" });
  },
  async bind() {
    if (this.data.busy) return;
    this.setData({ busy: true, error: "" });
    try {
      await api.request("account/" + this.data.mode, "POST", {
        login: this.data.login,
        password: this.data.password,
        ...this.source,
      });
      if (this.data.mode === "login") wx.setStorageSync("trupic.draft", null);
      this.source = {};
      this.setData({ password: "" });
      await this.load();
    } catch (e) {
      this.setData({ error: e.message });
    } finally {
      this.setData({ busy: false });
    }
  },
  async logout() {
    if (this.data.busy) return;
    this.setData({ busy: true });
    try {
      await api.request("account/logout", "POST", {});
      wx.setStorageSync("trupic.draft", null);
      getApp().globalData.preview = null;
      await this.load();
    } catch (e) {
      this.setData({ error: e.message });
    } finally {
      this.setData({ busy: false });
    }
  },
  copy(e) {
    wx.setClipboardData({ data: e.currentTarget.dataset.code });
  },
  onShareAppMessage(event) {
    const query = event.target?.dataset?.query || this.data.links[0]?.query;
    return {
      title: "一起做门店推广图文与短片",
      path: query ? "/pages/promotion/promotion?" + query : "/pages/home/home",
    };
  },
});
