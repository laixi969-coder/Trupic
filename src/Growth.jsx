import React, { useState, useEffect } from "react";
import { MerchantShop } from "./Commerce.jsx";
import { api, copyText } from "./ui.jsx";

const statuses = {
  pending: "待结算",
  disqualified: "审核未通过",
  payer_review: "代付待核对",
  settled: "已结算",
  reversed: "退款已冲回",
  recovered: "已追回",
  recovery_due: "已结算待追回",
};
const labels = {
  generateOwner: "首作 · 邀请人积分",
  generateGuest: "首作 · 新商家积分",
  paidOwner: "首付 · 邀请人积分",
  paidGuest: "首付 · 新商家积分",
  settleDays: "付款后等待结算天数",
  renewMonths: "续费分佣月数（0 为不限）",
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
              act({
                ...data.rules,
                expectedVersion: data.rules.version,
                action: "rules",
              });
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
                    max={
                      ["settleDays", "renewMonths"].includes(k) ? 3650 : 10000
                    }
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
            <div className="fieldgrid">
              {[
                ["starts", "活动开始日期（UTC）"],
                ["ends", "活动结束日期（UTC）"],
              ].map(([key, label]) => (
                <label className="field" key={key}>
                  {label}
                  <input
                    type="date"
                    value={data.rules[key]}
                    onChange={(e) =>
                      setData({
                        ...data,
                        rules: { ...data.rules, [key]: e.target.value },
                      })
                    }
                  />
                </label>
              ))}
              <label className="field">
                邀请与渠道同时归属
                <select
                  value={data.rules.overlap}
                  onChange={(e) =>
                    setData({
                      ...data,
                      rules: { ...data.rules, overlap: e.target.value },
                    })
                  }
                >
                  <option value="agent">渠道佣金优先</option>
                  <option value="merchant">邀请积分优先</option>
                  <option value="both">两项叠加</option>
                </select>
              </label>
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
          <details className="formpanel">
            <summary>渠道成员（{data.agents.length}）</summary>
            {data.agents.map((a) => (
              <p key={a.login}>
                {a.login} · {a.kind}
                {a.parent && " · 上级 " + a.parent} ·{" "}
                {a.enabled ? "已授权" : "已停用"}{" "}
                {a.enabled === 1 && (
                  <button
                    className="textbtn"
                    disabled={busy}
                    onClick={() =>
                      act({ action: "disable-agent", login: a.login })
                    }
                  >
                    停用渠道授权
                  </button>
                )}
              </p>
            ))}
          </details>
          <h3>归属核查</h3>
          {data.reviews.map((r) => (
            <div className="adminrow" key={r.id}>
              <span>
                {r.guest} · 申请{r.kind === "agent" ? "渠道" : "邀请"}归属 {r.owner}
              </span>
              <button
                className="secondary"
                disabled={busy}
                onClick={() => act({ action: "approve-transfer", id: r.id })}
              >
                {r.kind === "agent" ? "迁移后续订单" : "确认邀请归属"}
              </button>
              <button
                className="textbtn"
                disabled={busy}
                onClick={() => act({ action: "reject-transfer", id: r.id })}
              >
                保留原归属
              </button>
            </div>
          ))}
          {data.payments.length > 0 && (
            <section>
              <h3>付款核对</h3>
              {data.payments.map((p) => (
                <form
                  key={p.id}
                  className="formpanel"
                  onSubmit={(e) => {
                    e.preventDefault();
                    act({
                      action: e.nativeEvent.submitter.value,
                      order: p.id,
                      reference: new FormData(e.currentTarget).get("reference"),
                    });
                  }}
                >
                  <p>
                    {p.login} · 实付 ¥{(p.cents / 100).toFixed(2)} · {p.reason}
                  </p>
                  <p>
                    {p.id} · 付款人 {p.payer_login || "待确认"} · 渠道凭据{" "}
                    {p.payer || "待补充"}
                  </p>
                  <label className="field">
                    核对依据
                    <input name="reference" maxLength={120} required />
                  </label>
                  <button
                    className="secondary"
                    value="verify-payer"
                    disabled={busy}
                  >
                    核实付款并释放奖励
                  </button>
                  <button
                    className="textbtn"
                    value="reject-payer"
                    disabled={busy}
                  >
                    驳回本单奖励
                  </button>
                </form>
              ))}
            </section>
          )}
          <h3>佣金结算</h3>
          {data.commissions.map((c) => (
            <div className="adminrow" key={c.order_id}>
              <span>
                {c.merchant} · 渠道 {c.representative} · 订单 {c.order_id} ·
                佣金 ¥{(c.amount / 100).toFixed(2)}
              </span>
              {c.status === "pending" && c.available > data.asOf ? (
                "待结算 · " + c.available.slice(0, 10) + " 起可结算"
              ) : c.status === "pending" ? (
                <button
                  className="textbtn"
                  disabled={busy}
                  onClick={() => act({ action: "settle", order: c.order_id })}
                >
                  登记已结算
                </button>
              ) : c.status === "recovery_due" ? (
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    act({
                      action: "recover",
                      order: c.order_id,
                      reference: new FormData(e.currentTarget).get("reference"),
                    });
                  }}
                >
                  <label className="field">
                    核对凭证
                    <input name="reference" required maxLength={120} />
                  </label>
                  <button className="secondary" disabled={busy}>
                    登记已追回
                  </button>
                </form>
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
  const sharedCode = (k) => data.codes[k === "both" ? "merchant" : k];
  const link = (k) => {
    const url = new URL(location.pathname, location.origin);
    url.searchParams.set("invite", sharedCode(k));
    if (k === "both") url.searchParams.set("channel", data.channel);
    return url.href;
  };
  return (
    <section className="formpanel promotion-panel">
      {data &&
        (Object.keys(data.codes).length === 0 ? (
          <button className="secondary" onClick={onLogin}>
            绑定账号，获取邀请链接
          </button>
        ) : (
          Object.keys(data.codes)
            .concat(data.channel ? ["both"] : [])
            .map((k) => (
              <div key={k}>
                <label className="field">
                  {k === "both"
                    ? "商家与渠道联合推广链接"
                    : k === "agent"
                      ? "渠道推广链接"
                      : "商家邀请链接"}
                  <input readOnly value={link(k)} />
                </label>
                <button
                  className="secondary"
                  onClick={async () => {
                    try {
                      if (await copyText(link(k))) setMsg("链接已复制");
                      else setMsg("请选中上方链接复制");
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
                    src={
                      "/api/promotion/" +
                      sharedCode(k) +
                      "/qr" +
                      (k === "both" ? "?channel=" + data.channel : "")
                    }
                    alt="扫码打开邀请链接"
                  />
                </details>
              </div>
            ))
        ))}
      {msg && <p role="status">{msg}</p>}
      {data?.campaign && (
        <details>
          <summary>邀请奖励规则</summary>
          <p>
            好友首次完成图文或视频后，你获 {data.campaign.generateOwner}{" "}
            积分，好友获 {data.campaign.generateGuest} 积分。
          </p>
          <p>
            好友首次实付后，你获 {data.campaign.paidOwner} 积分，好友获{" "}
            {data.campaign.paidGuest} 积分。双方商户身份核实后入账。
          </p>
          {(data.campaign.starts || data.campaign.ends) && (
            <p>
              活动日期（UTC）{data.campaign.starts || "不限"} 至{" "}
              {data.campaign.ends || "不限"}
            </p>
          )}
        </details>
      )}
      {data?.rewards?.length > 0 && (
        <details>
          <summary>奖励明细</summary>
          {data.rewards.map((r) => (
            <p key={r.login + r.stage}>
              {r.login} · {r.stage === "paid" ? "首次实付" : "首次有效生成"} ·{" "}
              {r.amount} 积分 ·
              {r.payment === "refunded"
                ? "订单已退款"
                : r.eligible === 0
                  ? "未满足活动条件"
                  : r.issued
                    ? "已结算"
                    : "待核实商户身份"}
            </p>
          ))}
        </details>
      )}
      {data?.invites?.length > 0 && (
        <details>
          <summary>已邀请 {data.invites.length} 家商家</summary>
          {data.invites.map((i) => (
            <p key={i.login}>
              {i.login} · {i.created.slice(0, 10)} · 已核实并结算{" "}
              {i.rewardedStages}/2 个阶段
            </p>
          ))}
        </details>
      )}
      {data?.role && (
        <>
          <h3>{data.role}工作台</h3>
          {data.team.length > 0 && (
            <details>
              <summary>下属推广员（{data.team.length}）</summary>
              {data.team.map((a) => (
                <p key={a.login}>
                  {a.login} · {a.kind}
                </p>
              ))}
            </details>
          )}
          <p>归属客户 {data.clients.length} 家</p>
          {data.clients.map((c) => (
            <p key={c.login}>
              {c.login} · {c.representative} · {c.created.slice(0, 10)}{" "}
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
          <details>
            <summary>渠道订单（{data.orders.length}）</summary>
            {data.orders.map((o) => (
              <p key={o.id}>
                {o.login} · {o.name} · ¥{(o.cents / 100).toFixed(2)} ·
                {
                  {
                    pending: "待付款",
                    paid: "已支付",
                    refunded: "已退款",
                    cancelled: "已关闭",
                  }[o.state]
                }{" "}
                · {o.created.slice(0, 10)}
              </p>
            ))}
          </details>
          {data.commissions.map((c) => (
            <p key={c.order_id}>
              {c.login} · 实收 ¥{(c.cents / 100).toFixed(2)} · 佣金 ¥
              {(c.amount / 100).toFixed(2)} ·{" "}
              {c.status === "pending" &&
              (!c.available || c.available <= data.asOf)
                ? "可结算"
                : statuses[c.status]}
            </p>
          ))}
        </>
      )}
    </section>
  );
}
