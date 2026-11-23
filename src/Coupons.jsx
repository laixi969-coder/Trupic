import React, { useEffect, useState } from "react";
import { api } from "./ui.jsx";
export default function Coupons({ offers, tip }) {
  const [list, setList] = useState([]),
    [form, set] = useState({
      discount: 1,
      threshold: 0,
      quantity: 1,
      per_user: 1,
    }),
    [err, setErr] = useState(""),
    [busy, setBusy] = useState(false);
  const [records, setRecords] = useState({});
  useEffect(() => {
    api("/admin/coupons")
      .then(setList)
      .catch((e) => setErr(e.message));
  }, []);
  return (
    <details className="formpanel">
      <summary>优惠券与核销</summary>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setErr("");
          try {
            setList(await api("/admin/coupons", "POST", form));
            tip("券码已创建");
          } catch (e) {
            setErr(e.message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <label className="field">
          适用套餐
          <select
            required
            value={form.offer || ""}
            onChange={(e) => set({ ...form, offer: e.target.value })}
          >
            <option value="">选择套餐</option>
            {offers
              .filter((o) => o.enabled)
              .map((o) => (
                <option value={o.id} key={o.id}>
                  {o.name}
                </option>
              ))}
          </select>
        </label>
        {[
          ["discount", "减免金额（分）", "number"],
          ["threshold", "使用门槛（分）", "number"],
          ["quantity", "总量", "number"],
          ["per_user", "每人次数", "number"],
          ["starts", "开始日期", "date"],
          ["ends", "结束日期", "date"],
          ["agent", "渠道账号（选填）", "text"],
        ].map(([k, l, type]) => (
          <label key={k} className="field">
            {l}
            <input
              required={k !== "agent"}
              type={type}
              min={type === "number" ? 0 : undefined}
              value={form[k] ?? ""}
              onChange={(e) =>
                set({
                  ...form,
                  [k]:
                    type === "number" ? Number(e.target.value) : e.target.value,
                })
              }
            />
          </label>
        ))}
        <button disabled={busy} className="secondary">
          创建券码
        </button>
      </form>
      {err && <p role="alert">{err}</p>}
      {list.map((c) => (
        <details
          key={c.code}
          onToggle={async (e) => {
            if (!e.currentTarget.open) return;
            try {
              const entries = await api(
                "/admin/coupons/" + c.code + "/redemptions",
              );
              setRecords((prev) => ({ ...prev, [c.code]: entries }));
            } catch (e) {
              setErr(e.message);
            }
          }}
        >
          <summary>
            {c.name} · 券码 {c.code} · 已核销 {c.redeemed}/{c.quantity}
          </summary>
          {records[c.code]?.map((r) => (
            <p key={r.order_id}>
              {r.login} · {r.order_id} · ¥{(r.cents / 100).toFixed(2)} ·
              {
                {
                  paid: "已核销",
                  reserved: "已预留",
                  cancelled: "已取消",
                  refunded: "已退款",
                }[r.status]
              }
            </p>
          ))}
          {records[c.code]?.length === 0 && <p>暂无使用记录</p>}
        </details>
      ))}
    </details>
  );
}
