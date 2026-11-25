import React, { useState, useEffect } from "react";
import { Support } from "./Support.jsx";
import { api, dateText } from "./ui.jsx";
const taskStates = { queued: "等待制作", running: "正在制作", failed: "制作中断", complete: "已完成" };
const orderStates = { pending: "待支付", paid: "已支付", refunded: "已退款", cancelled: "已关闭" };
const money = (cents) => "¥" + (cents / 100).toFixed(2);
export default function Merchants({ role, tip }) {
  const [list, setList] = useState([]),
    [detail, setDetail] = useState(null),
    [f, set] = useState({
      login: "",
      role: "",
      reason: "",
      ref: "",
      amount: "",
    }),
    [err, setErr] = useState(""),
    [busy, setBusy] = useState(false);
  // The superuser, finance and support may read one merchant's profile, tasks, orders and ledger.
  const canInspect = !role || role === "finance" || role === "support";
  async function load() {
    setList(await api("/admin/merchants"));
  }
  useEffect(() => {
    load().catch((e) => setErr(e.message));
  }, []);
  useEffect(() => {
    setDetail(null);
    if (!f.login || !canInspect) return;
    let active = true;
    api("/admin/merchants/" + encodeURIComponent(f.login))
      .then((d) => {
        if (active) setDetail(d);
      })
      .catch((e) => {
        if (active) setErr(e.message);
      });
    return () => {
      active = false;
    };
  }, [f.login, canInspect]);
  async function act(path) {
    setBusy(true);
    setErr("");
    try {
      await api("/admin/" + path, "POST", f);
      await load();
      tip("操作已记录");
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="formpanel">
      <h2>商家与权限</h2>
      <label className="field">
        商家账号
        <select
          value={f.login}
          onChange={(e) => set({ ...f, login: e.target.value })}
        >
          <option value="">选择商家</option>
          {list.map((m) => (
            <option key={m.login}>{m.login}</option>
          ))}
        </select>
      </label>
      {list
        .filter((m) => m.login === f.login)
        .map((m) => (
          <p key={m.login}>
            {m.credits} 积分 · {m.tasks} 个任务 · {m.orders} 笔已付订单
          </p>
        ))}
      {detail && (
        <details open>
          <summary>商家档案与记录</summary>
          <div className="datarows">
            {[
              ["商家名称", detail.profile.name || "未填写"],
              ["经营行业", detail.profile.industryTags?.join("、") || detail.profile.industry || "未填写"],
              ["主要商品或服务", detail.profile.product || "未填写"],
              ["所在地区", detail.profile.city || "未填写"],
              ["注册时间", dateText(detail.created)],
              ["后台角色", detail.role === "operations" ? "运营" : detail.role === "finance" ? "财务" : detail.role === "support" ? "客服" : "无"],
            ].map(([k, v]) => (
              <div key={k}>
                <span>{k}</span>
                <b>{v}</b>
              </div>
            ))}
          </div>
          <h3>最近任务</h3>
          {detail.jobs.length ? detail.jobs.map((j) => (
            <p key={j.id}>
              {taskStates[j.state] || j.state} · {j.brief} · {j.cost} 积分 · {dateText(j.created)}
              {j.state === "failed" && j.error ? " · " + j.error : ""}
              {j.state === "running" && j.stage ? " · " + j.stage : ""}
            </p>
          )) : <p>暂无任务</p>}
          <h3>订单</h3>
          {detail.orders.length ? detail.orders.map((o) => (
            <p key={o.id}>{o.name} · {money(o.cents)} · {orderStates[o.state]} · {dateText(o.created)}</p>
          )) : <p>暂无订单</p>}
          <h3>积分流水</h3>
          {detail.ledger.length ? detail.ledger.map((l, i) => (
            <p key={i}>{l.note} · {l.delta > 0 ? "+" : ""}{l.delta} · {dateText(l.created)}</p>
          )) : <p>暂无流水</p>}
        </details>
      )}
      {!role && (
        <>
          <label className="field">
            管理员角色
            <select
              value={f.role}
              onChange={(e) => set({ ...f, role: e.target.value })}
            >
              {[
                ["", "无"],
                ["operations", "运营"],
                ["finance", "财务"],
                ["support", "客服"],
              ].map(([k, l]) => (
                <option key={k} value={k}>
                  {l}
                </option>
              ))}
            </select>
          </label>
          <button
            className="secondary"
            disabled={busy || !f.login}
            onClick={() => act("staff")}
          >
            保存权限
          </button>
        </>
      )}
      {role !== "support" && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            act("credits");
          }}
        >
          <h3>积分调整</h3>
          {[
            ["amount", "积分（扣减填负数）"],
            ["ref", "关联任务或业务单号"],
            ["reason", "调整原因"],
          ].map(([k, l]) => (
            <label className="field" key={k}>
              {l}
              <input
                required
                type={k === "amount" ? "number" : "text"}
                value={f[k]}
                onChange={(e) =>
                  set({
                    ...f,
                    [k]:
                      k === "amount" ? Number(e.target.value) : e.target.value,
                  })
                }
              />
            </label>
          ))}
          <button className="secondary" disabled={busy || !f.login}>
            确认调整
          </button>
        </form>
      )}
      {(!role || role === "support") && <Support admin />}
      {err && <p role="alert">{err}</p>}
    </section>
  );
}
