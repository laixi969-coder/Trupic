import React, { useEffect, useState, useRef } from "react";
import Coupons from "./Coupons.jsx";
import { api } from "./ui.jsx";

const cycles = {
  month: "月付",
  year: "年付",
  quarter: "季付（后台储备）",
  pack: "积分包",
};
const labels = {
  copy: "文案",
  poster: "每张图片",
  video: "体验短片",
  video30: "30 秒短片",
  video45: "45 秒短片",
  revision: "每次修改",
  trial: "新商家体验额度",
  trialDays: "体验有效天数",
};
const money = (cents) => "¥" + (cents / 100).toFixed(2);
const initialOffer = {
  name: "",
  cycle: "month",
  cents: "",
  credits: "",
  bonus: 0,
  carry_cap: 0,
};

function TaskCosts() {
  const [rows, setRows] = useState([]),
    [filter, setFilter] = useState(""),
    [err, setErr] = useState(""),
    [busy, setBusy] = useState(false);
  async function load() {
    setErr("");
    try {
      setRows(await api("/admin/task-costs?job=" + encodeURIComponent(filter)));
    } catch (e) {
      setErr(e.message);
    }
  }
  return (
    <details
      className="formpanel"
      onToggle={(e) => {
        if (e.target === e.currentTarget && e.currentTarget.open) load();
      }}
    >
      <summary>逐任务成本与毛利</summary>
      <p>
        收入按该任务消耗的积分占原单全部权益的比例分摊。模型毛利为分摊收入减已核对的模型成本，单位为人民币元。
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          load();
        }}
      >
        <label className="field">
          任务编号
          <input value={filter} onChange={(e) => setFilter(e.target.value)} />
        </label>
        <button className="secondary">查询</button>
      </form>
      {err && <p role="alert">{err}</p>}
      {rows.map((r) => (
        <details key={r.id}>
          <summary>
            {r.brief} · 模型毛利 {r.margin ?? "待核对"}
          </summary>
          <p>
            {r.id} · 已关联模型调用 {r.calls} 次 · 分摊收入{" "}
            {r.revenue ?? "待核对"} · 模型成本 {r.modelCost ?? "待核对"}
          </p>
          {["complete", "failed"].includes(r.state) && (
            <form
              onSubmit={async (e) => {
                e.preventDefault();
                const f = new FormData(e.currentTarget);
                setBusy(true);
                setErr("");
                try {
                  await api("/admin/task-costs", "POST", {
                    job: r.id,
                    amount: f.get("amount"),
                    source: f.get("source"),
                  });
                  await load();
                } catch (error) {
                  setErr(error.message);
                } finally {
                  setBusy(false);
                }
              }}
            >
              <label className="field">
                该任务实际模型成本（元）
                <input
                  type="number"
                  name="amount"
                  min="0"
                  step="0.000001"
                  defaultValue={r.modelCost}
                  required
                />
              </label>
              <label className="field">
                账单编号与核对依据
                <input
                  name="source"
                  maxLength={220}
                  defaultValue={r.source}
                  required
                />
              </label>
              <button className="secondary" disabled={busy}>
                保存任务对账
              </button>
            </form>
          )}
        </details>
      ))}
    </details>
  );
}

export function FinanceAdmin({ tip }) {
  const [rates, setRates] = useState(null),
    [offers, setOffers] = useState([]);
  const [form, setForm] = useState(initialOffer),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function load() {
    const [r, o] = await Promise.all([
      api("/admin/pricing"),
      api("/admin/offers"),
    ]);
    setRates(r);
    setOffers(o);
  }
  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, []);
  async function save(fn) {
    setBusy(true);
    setError("");
    try {
      await fn();
      await load();
      tip("已保存");
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {rates && (
        <form
          className="formpanel"
          onSubmit={(e) => {
            e.preventDefault();
            save(() => api("/admin/pricing", "POST", rates));
          }}
        >
          <h2>积分定价</h2>
          <div className="fieldgrid">
            {Object.entries(labels).map(([id, label]) => (
              <label className="field" key={id}>
                {label}
                <input
                  type="number"
                  required
                  min={["trialDays", "revision"].includes(id) ? 1 : 0}
                  value={rates[id]}
                  onChange={(e) =>
                    setRates({
                      ...rates,
                      [id]: e.target.value === "" ? "" : Number(e.target.value),
                    })
                  }
                />
              </label>
            ))}
          </div>
          <button className="primary" disabled={busy}>
            保存定价
          </button>
        </form>
      )}
      <form
        className="formpanel"
        onSubmit={(e) => {
          e.preventDefault();
          save(async () => {
            await api("/admin/offers", "POST", form);
            setForm(initialOffer);
          });
        }}
      >
        <h2>新增套餐或积分包</h2>
        <div className="fieldgrid">
          <label className="field">
            名称
            <input
              required
              maxLength={60}
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
          </label>
          <label className="field">
            周期
            <select
              value={form.cycle}
              onChange={(e) =>
                setForm({
                  ...form,
                  cycle: e.target.value,
                  carry_cap: e.target.value === "pack" ? 0 : form.carry_cap,
                })
              }
            >
              {Object.entries(cycles).map(([k, v]) => (
                <option value={k} key={k}>
                  {v}
                </option>
              ))}
            </select>
          </label>
          {[
            ["cents", "售价（分）"],
            ["credits", form.cycle === "pack" ? "积分包额度" : "每月积分"],
            ["bonus", "订单赠分"],
            ...(form.cycle === "pack"
              ? []
              : [["carry_cap", "每月可结转至下月的积分上限"]]),
          ].map(([k, v]) => (
            <label key={k} className="field">
              {v}
              <input
                required
                type="number"
                min={["bonus", "carry_cap"].includes(k) ? 0 : 1}
                value={form[k]}
                onChange={(e) =>
                  setForm({
                    ...form,
                    [k]: e.target.value === "" ? "" : Number(e.target.value),
                  })
                }
              />
            </label>
          ))}
        </div>
        <button className="primary" disabled={busy}>
          {form.cycle === "quarter" ? "保存后台方案" : "上架"}
        </button>
      </form>
      <Coupons offers={offers} tip={tip} />
      <TaskCosts />
      {offers.map((o) => (
        <div className="adminrow" key={o.id}>
          <span>
            {o.name} · {cycles[o.cycle]} · {money(o.cents)}
          </span>
          {o.enabled ? (
            <button
              className="textbtn"
              disabled={busy}
              onClick={() =>
                save(() =>
                  api("/admin/offers/" + o.id + "/disable", "POST", {}),
                )
              }
            >
              下架
            </button>
          ) : (
            "已下架"
          )}
        </div>
      ))}
    </section>
  );
}

export function MerchantShop({ merchant = "" }) {
  const [shop, setShop] = useState(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const keys = useRef({});
  const [coupon, setCoupon] = useState(""),
    [quote, setQuote] = useState(null);
  const shopPath = merchant
    ? "/shop?merchant=" + encodeURIComponent(merchant)
    : "/shop";
  useEffect(() => {
    api(shopPath)
      .then(setShop)
      .catch((e) => setError(e.message));
  }, [shopPath]);
  async function price(o) {
    setError("");
    setBusy(true);
    try {
      const q = await api("/orders/price", "POST", {
        offer: o.id,
        coupon,
        merchant,
      });
      setQuote({ ...q, offer: o, coupon });
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function buy(o) {
    setBusy(true);
    setError("");
    try {
      const key = JSON.stringify([o.id, quote.coupon, quote.cents]);
      keys.current[key] ||= crypto.randomUUID();
      const r = await api("/orders", "POST", {
        merchant,
        offer: o.id,
        cents: quote.cents,
        coupon: quote.coupon,
        credits: o.credits,
        bonus: o.bonus,
        requestKey: keys.current[key],
      });
      setShop(await api(shopPath));
      if (r.checkout) location.assign(r.checkout);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section>
      <h4>套餐与订单</h4>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {shop?.subscription && (
        <p>套餐有效至 {shop.subscription.ends.slice(0, 10)}</p>
      )}
      {!!shop?.offers.length && (
        <label className="field">
          优惠券码（选填）
          <input
            value={coupon}
            onChange={(e) => {
              setCoupon(e.target.value);
              setQuote(null);
            }}
          />
        </label>
      )}
      {quote && (
        <p>
          确认购买 {quote.offer.name} · 实付 {money(quote.cents)}{" "}
          <button
            className="secondary"
            disabled={busy}
            onClick={() => buy(quote.offer)}
          >
            确认并前往支付
          </button>
        </p>
      )}
      {shop?.offers.map((o) => (
        <div className="adminrow" key={o.id}>
          <div>
            <b>
              {o.name} · {cycles[o.cycle]}
            </b>
            <p>
              {o.credits} 积分{o.cycle === "pack" ? "" : "/月"}
              {o.carry_cap > 0 &&
                " · 当月余额最多可结转 " + o.carry_cap + " 积分至下月"}
              {o.bonus > 0 && " · 另赠 " + o.bonus + " 积分"}
            </p>
          </div>
          <button
            className="secondary"
            disabled={!shop.canPay || busy}
            onClick={() => price(o)}
          >
            {money(o.cents)} · {shop.canPay ? "去支付" : "支付暂未开通"}
          </button>
        </div>
      ))}
      {shop && !shop.offers.length && <p>暂无上架套餐</p>}
      {shop?.orders.map((o) => (
        <p key={o.id}>
          {o.name} · {money(o.cents)} ·{" "}
          {
            {
              paid: "已支付",
              pending: "待支付",
              refunded: "已退款",
              cancelled: "已关闭",
            }[o.state]
          }{" "}
          {o.checkout && <a href={o.checkout}>继续支付</a>}
        </p>
      ))}
    </section>
  );
}
