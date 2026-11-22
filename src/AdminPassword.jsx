import React, { useState } from "react";
import { api } from "./ui.jsx";

export default function AdminPassword({ config, refresh, tip }) {
  const [currentPassword, setCurrent] = useState("");
  const [newPassword, setNew] = useState("");
  const [confirmPassword, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  async function save(event) {
    event.preventDefault();
    if (busy) return;
    setError(""); setSaved(false);
    if (newPassword !== confirmPassword) { setError("两次输入的新密码不一致。"); return; }
    setBusy(true);
    try {
      await api("/admin/password", "POST", { currentPassword, newPassword, confirmPassword });
      setCurrent(""); setNew(""); setConfirm(""); setSaved(true);
      tip("管理密码已更新，其他管理会话需要重新登录。");
      await refresh();
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }
  return <section className="admin-password">
    <h2>管理密码</h2>
    <p>管理密码用于运营后台，与商家账号密码分别管理。</p>
    {config.environmentManaged ? <p role="status">当前由启动环境 TRUPIC_ADMIN_KEY 指定。请在启动配置中修改该值并重启服务，页面中的密码设置不会覆盖它。</p> : <>
      <p>{config.customPassword ? "已设置自定义管理密码。" : "当前使用首次启动时生成的初始密钥。可在项目数据目录的 admin.key 文件中查看，默认位置为 .trupic/admin.key。"}</p>
      <form onSubmit={save}>
        <label className="field">当前管理密码<input type="password" autoComplete="current-password" required maxLength={160} value={currentPassword} onChange={(e) => setCurrent(e.target.value)} disabled={busy} /></label>
        <label className="field">新管理密码<input type="password" autoComplete="new-password" required minLength={8} maxLength={160} placeholder="8–160 位，首尾不含空格" value={newPassword} onChange={(e) => setNew(e.target.value)} disabled={busy} /></label>
        <label className="field">再次输入新密码<input type="password" autoComplete="new-password" required minLength={8} maxLength={160} value={confirmPassword} onChange={(e) => setConfirm(e.target.value)} disabled={busy} /></label>
        {error && <p className="error" role="alert">{error}</p>}
        {saved && <p role="status">管理密码已更新。以后请用新密码登录，初始密钥已失效。</p>}
        <button className="primary" disabled={busy}>{busy ? "正在保存…" : "保存管理密码"}</button>
      </form>
      <p className="muted">修改后立即生效，其他已登录的管理会话需要重新登录。</p>
    </>}
  </section>;
}
