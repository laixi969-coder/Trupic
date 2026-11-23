import React, { useState, useEffect } from "react";
import { MerchantShop } from "./Commerce.jsx";
import { api } from "./ui.jsx";

const statuses = {
  pending: "待结算",
  settled: "已结算",
  reversed: "退款已冲回",
  recovery_due: "已结算待追回",
};
const labels = {
  generateOwner: "首作 · 邀请人积分",
  generateGuest: "首作 · 新商家积分",
  paidOwner: "首付 · 邀请人积分",
  paidGuest: "首付 · 新商家积分",
  firstBps: "首单佣金（万分比）",
  renewBps: "续费佣金（万分比）",
};

export function GrowthAdmin({ tip }) {
  const [data, setData] = useState(null),
    [form, setForm] = useState({
      role: "个人推广员",
      login: "",
      parent: "",
      identity: "",
    }),
    [err, setErr] = useState(""),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    api("/admin/growth")
      .then(setData)
      .catch((e) => setErr(e.message));
  }, []);
  async function act(v) {
    setBusy(true);
    setErr("");
    try {
      setData(await api("/admin/growth", "POST", v));
      tip("已保存");
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section>
      {err && <p role="alert">{err}</p>}
      {data && (
        <>
          <form
            className="formpanel"
            onSubmit={(e) => {
              e.preventDefault();
              act({ ...data.rules, action: "rules" });
            }}
          >
            <h2>邀请奖励与佣金</h2>
            <div className="fieldgrid">
              {Object.entries(labels).map(([k, l]) => (
                <label className="field" key={k}>
                  {l}
                  <input
                    type="number"
                    required
                    min="0"
                    max="10000"
                    value={data.rules[k]}
                    onChange={(e) =>
                      setData({
                        ...data,
                        rules: {
                          ...data.rules,
                          [k]:
                            e.target.value === "" ? "" : Number(e.target.value),
                        },
                      })
                    }
                  />
                </label>
              ))}
            </div>
            <button className="primary" disabled={busy}>
              保存规则
            </button>
          </form>
          <section className="formpanel">
            <h2>商家与渠道归属</h2>
            <label className="field">
              已绑定的商家账号
              <input
                value={form.login}
                onChange={(e) => setForm({ ...form, login: e.target.value })}
              />
            </label>
            <label className="field">
              已核实的唯一商户编号
              <input
                value={form.identity}
                onChange={(e) => setForm({ ...form, identity: e.target.value })}
              />
            </label>
            <button
              className="secondary"
              disabled={busy || !form.identity || !form.login}
              onClick={() => act({ ...form, action: "verify" })}
            >
              核实商户身份
            </button>
            <label className="field">
              渠道角色
              <select
                value={form.role}
                onChange={(e) => setForm({ ...form, role: e.target.value })}
              >
                {["个人推广员", "团队负责人", "区县代理"].map((r) => (
                  <option key={r}>{r}</option>
                ))}
              </select>
            </label>
            <label className="field">
              上级账号（选填）
              <input
                value={form.parent}
                onChange={(e) => setForm({ ...form, parent: e.target.value })}
              />
            </label>
            <button
              className="secondary"
              disabled={busy || !form.login}
              onClick={() => act({ ...form, action: "agent" })}
            >
              保存渠道授权
            </button>
          </section>
          <h3>归属核查</h3>
          {data.reviews.map((r) => (
            <div className="adminrow" key={r.id}>
              <span>
                {r.guest} · 申请归属 {r.owner}
              </span>
              {r.kind === "agent" && (
                <button
                  className="secondary"
                  disabled={busy}
                  onClick={() => act({ action: "approve-transfer", id: r.id })}
                >
                  迁移后续订单
                </button>
              )}
              <button
                className="textbtn"
                disabled={busy}
                onClick={() => act({ action: "reject-transfer", id: r.id })}
              >
                保留原归属
              </button>
            </div>
          ))}
          <h3>佣金结算</h3>
          {data.commissions.map((c) => (
            <div className="adminrow" key={c.order_id}>
              <span>
                订单 {c.order_id} · 佣金 ¥{(c.amount / 100).toFixed(2)}
              </span>
              {c.status === "pending" ? (
                <button
                  className="textbtn"
                  disabled={busy}
                  onClick={() => act({ action: "settle", order: c.order_id })}
                >
                  登记已结算
                </button>
              ) : (
                statuses[c.status]
              )}
            </div>
          ))}
        </>
      )}
    </section>
  );
}

export function Promotion({ onLogin }) {
  const [data, setData] = useState(null),
    [msg, setMsg] = useState("");
  const [client, setClient] = useState("");
  useEffect(() => {
    api("/promotion")
      .then(setData)
      .catch((e) => setMsg(e.message));
  }, []);
  const link = (k) =>
    location.origin + location.pathname + "?invite=" + data.codes[k];
  return (
    <section className="formpanel">
      <h2>邀请与推广</h2>
      {data &&
        (Object.keys(data.codes).length === 0 ? (
          <button className="secondary" onClick={onLogin}>
            绑定账号，获取邀请链接
          </button>
        ) : (
          Object.keys(data.codes).map((k) => (
            <div key={k}>
              <label className="field">
                {k === "agent" ? "渠道推广链接" : "商家邀请链接"}
                <input readOnly value={link(k)} />
              </label>
              <button
                className="secondary"
                onClick={async () => {
                  try {
                    await navigator.clipboard.writeText(link(k));
                    setMsg("链接已复制");
                  } catch {
                    setMsg("请选中上方链接复制");
                  }
                }}
              >
                复制链接
              </button>
              <details>
                <summary>查看推广二维码</summary>
                <img
                  width="180"
                  height="180"
                  src={"/api/promotion/" + data.codes[k] + "/qr"}
                  alt="扫码打开邀请链接"
                />
              </details>
            </div>
          ))
        ))}
      {msg && <p role="status">{msg}</p>}
      {data?.role && (
        <>
          <h3>{data.role}工作台</h3>
          <p>归属客户 {data.clients.length} 家</p>
          {data.clients.map((c) => (
            <p key={c.login}>
              {c.login} · {c.created.slice(0, 10)}{" "}
              <button className="textbtn" onClick={() => setClient(c.login)}>
                协助订购
              </button>
            </p>
          ))}
          {client && (
            <section>
              <h4>为 {client} 订购</h4>
              <MerchantShop key={client} merchant={client} />
            </section>
          )}
          {data.coupons.map((c) => (
            <p key={c.code}>
              可发放优惠券 · {c.name} · {c.code} · 有效至 {c.ends}
            </p>
          ))}
          {data.commissions.map((c) => (
            <p key={c.order_id}>
              {c.login} · 实收 ¥{(c.cents / 100).toFixed(2)} · 佣金 ¥
              {(c.amount / 100).toFixed(2)} · {statuses[c.status]}
            </p>
          ))}
        </>
      )}
    </section>
  );
}
