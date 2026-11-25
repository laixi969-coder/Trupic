// Plans and credit packs. Payment opens in the merchant's browser from a copied link.
const api = require("../../lib/api");

const cycles = { month: "月付", year: "年付", pack: "积分包" };
const states = { pending: "待付款", paid: "已付款", closed: "已关闭", refunded: "已退款" };

Page({
  data: { offers: [], orders: [], subscription: "", account: "", canPay: false, busy: "", error: "" },
  onShow() {
    return this.load();
  },
  async load() {
    try {
      const [shop, state] = await Promise.all([api.request("shop"), api.request("state")]);
      this.setData({
        offers: shop.offers.map((o) => ({
          ...o,
          cycleName: cycles[o.cycle],
          money: (o.cents / 100).toFixed(2),
        })),
        orders: shop.orders.map((o) => ({ ...o, stateName: states[o.state] || o.state, money: (o.cents / 100).toFixed(2) })),
        subscription: shop.subscription ? "有效期至 " + String(shop.subscription.ends).slice(0, 10) : "",
        canPay: shop.canPay,
        account: state.login || "",
        credits: state.credits,
        error: "",
      });
    } catch (e) {
      this.setData({ error: e.message });
    }
  },
  async buy(e) {
    const offer = this.data.offers.find((o) => o.id === e.currentTarget.dataset.id);
    if (this.data.busy || !offer) return;
    this.setData({ busy: offer.id });
    try {
      if (!this.requestKey || this.offer !== offer.id) {
        this.offer = offer.id;
        this.requestKey = "wx-" + Date.now() + "-" + Math.random().toString(36).slice(2);
      }
      const order = await api.request("orders", "POST", {
        offer: offer.id,
        cents: offer.cents,
        credits: offer.credits,
        bonus: offer.bonus,
        requestKey: this.requestKey,
      });
      if (!order.checkout) throw new Error("订单已创建，付款链接暂时无法生成，请稍后在订单列表重试。");
      wx.setClipboardData({ data: order.checkout });
      wx.showModal({
        title: "订单已创建",
        content: "付款链接已复制，请在手机浏览器打开并完成支付。付款后回到这里刷新，积分会自动到账。",
        showCancel: false,
      });
      await this.load();
    } catch (e) {
      api.message(e);
    } finally {
      this.setData({ busy: "" });
    }
  },
  copyOrder(e) {
    const order = this.data.orders.find((o) => o.id === e.currentTarget.dataset.id);
    if (order?.checkout) wx.setClipboardData({ data: order.checkout });
  },
  account() {
    wx.navigateTo({ url: "/pages/promotion/promotion" });
  },
});
