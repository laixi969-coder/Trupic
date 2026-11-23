import React, { useState, useEffect } from "react";
import { api } from "./ui.jsx";
export default function Merchants({ role, tip }) {
  const [list, setList] = useState([]),
    [f, set] = useState({
      login: "",
      role: "",
      reason: "",
      ref: "",
      amount: "",
    }),
    [err, setErr] = useState(""),
    [busy, setBusy] = useState(false);
  async function load() {
    setList(await api("/admin/merchants"));
  }
  useEffect(() => {
    load().catch((e) => setErr(e.message));
  }, []);
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
      {err && <p role="alert">{err}</p>}
    </section>
  );
}
