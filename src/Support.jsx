import React, { useState, useEffect } from "react";
import { api } from "./ui.jsx";

export function Support({ work, admin = false }) {
  const [items, setItems] = useState([]),
    [message, setMessage] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const path = admin ? "/admin/complaints" : "/complaints";
  const listPath = admin ? path : path + "?work=" + encodeURIComponent(work);
  useEffect(() => {
    let active = true;
    api(listPath)
      .then((rows) => {
        if (active) setItems(rows);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [listPath]);
  async function submit(data) {
    setBusy(true);
    setError("");
    try {
      await api(path, "POST", data);
      setItems(await api(listPath));
      setMessage("");
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <details className="formpanel">
      <summary>{admin ? "商家售后反馈" : "作品有问题？联系平台"}</summary>
      {!admin && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            submit({ work, message });
          }}
        >
          <label className="field">
            问题描述
            <textarea
              required
              maxLength={500}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
            />
          </label>
          <button className="secondary" disabled={busy || !message.trim()}>
            提交反馈
          </button>
        </form>
      )}
      {error && <p role="alert">{error}</p>}
      {items.map((row) => (
        <section key={row.id}>
          <p>
            {admin && (row.login || "体验商家") + " · "}
            {row.message}
          </p>
          {row.reply ? (
            <p>平台回复 · {row.reply}</p>
          ) : admin ? (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                submit({
                  id: row.id,
                  reply: new FormData(e.currentTarget).get("reply"),
                });
              }}
            >
              <label className="field">
                处理结果
                <input name="reply" maxLength={500} required />
              </label>
              <button className="secondary" disabled={busy}>
                登记处理结果
              </button>
            </form>
          ) : (
            <small>等待处理</small>
          )}
        </section>
      ))}
      {admin && !items.length && <p>暂无反馈</p>}
    </details>
  );
}
