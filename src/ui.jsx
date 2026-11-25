import React, { useEffect, useRef } from "react";
import {
  Image as ImageIcon,
  FileText,
  Clapperboard,
  X,
  LoaderCircle,
  ArrowUpRight,
  Plus,
} from "lucide-react";
export const formats = {
  poster: { name: "营销海报", icon: ImageIcon },
  copy: { name: "推广文案", icon: FileText },
  video: { name: "宣传短片", icon: Clapperboard },
};
export const imageUrl = (id) => "/visuals/" + id + ".webp";
export const dateText = (value) =>
  new Date(value).toLocaleDateString("zh-CN", {
    month: "short",
    day: "numeric",
  });
export async function api(path, method = "GET", data) {
  const form = data instanceof FormData;
  const response = await fetch("/api" + path, {
    method,
    headers: data && !form ? { "Content-Type": "application/json" } : {},
    body: data ? (form ? data : JSON.stringify(data)) : undefined,
  });
  let result;
  try {
    result = await response.json();
  } catch {
    throw new Error("服务暂时无法连接，请稍后重试。");
  }
  if (!response.ok) throw new Error(result.error || "操作失败，请重试。");
  return result;
}
export async function copyText(text) {
  // The Clipboard API needs a secure origin. Local network testing over http
  // falls back to a temporary selection, which still works inside a tap.
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {}
  }
  const field = document.createElement("textarea");
  field.value = text;
  field.setAttribute("readonly", "");
  field.style.cssText = "position:fixed;top:0;left:0;opacity:0";
  document.body.appendChild(field);
  const picked = document.getSelection();
  const range = picked?.rangeCount ? picked.getRangeAt(0) : null;
  field.select();
  field.setSelectionRange(0, text.length);
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch {}
  field.remove();
  if (range) {
    picked.removeAllRanges();
    picked.addRange(range);
  }
  return ok;
}
export function Brand() {
  return (
    <div className="brand">
      <img src="/favicon.svg" alt="" />
      <div>
        <strong>
          Trupic<span>.</span>
        </strong>
        <small>响指出片</small>
      </div>
    </div>
  );
}
export function Modal({ title, children, onClose, wide = false }) {
  const ref = useRef(),
    close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const prior = document.activeElement;
    const focus = () =>
      Array.from(
        ref.current?.querySelectorAll(
          'button:not([disabled]),input:not([disabled]),textarea,select,a[href],[tabindex="0"]',
        ) || [],
      ).filter((n) => n.offsetParent !== null);
    focus()[0]?.focus();
    const fn = (e) => {
      if (e.key === "Escape") close.current?.();
      if (e.key === "Tab") {
        const els = focus(),
          first = els[0],
          last = els.at(-1);
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last?.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener("keydown", fn);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", fn);
      document.body.style.overflow = overflow;
      prior?.focus();
    };
  }, []);
  return (
    <div
      className="overlay"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose?.();
      }}
    >
      <section
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={"modal " + (wide ? "wide" : "")}
      >
        <header>
          <h2>{title}</h2>
          {onClose && (
            <button className="iconbtn" aria-label="关闭" onClick={onClose}>
              <X size={19} />
            </button>
          )}
        </header>
        {children}
      </section>
    </div>
  );
}
export function PageHead({ title, desc, children }) {
  return (
    <div className="pagehead">
      <div>
        <h1>{title}</h1>
        {desc && <p>{desc}</p>}
      </div>
      {children}
    </div>
  );
}
export function Blank({
  icon: Icon = ImageIcon,
  title,
  desc,
  action,
  onClick,
}) {
  return (
    <div className="empty">
      <span className="empty-icon">
        <Icon size={28} />
      </span>
      <h3>{title}</h3>
      <p>{desc}</p>
      {action && (
        <button className="primary" onClick={onClick}>
          <Plus size={16} />
          {action}
        </button>
      )}
    </div>
  );
}
export function Busy({ text = "正在处理…" }) {
  return (
    <span className="inline">
      <LoaderCircle size={16} className="spin" />
      {text}
    </span>
  );
}
export function CaseCard({ item, onClick }) {
  return (
    <button className="casecard" onClick={() => onClick(item)}>
      <div className="caseimg">
        <img src={imageUrl(item.id)} alt={item.title} />
        <span className="case-format">
          <ImageIcon size={12} />
          海报
        </span>
        <span className="case-open">
          <ArrowUpRight size={17} />
        </span>
      </div>
      <div className="case-meta">
        <span className={"catdot " + item.id} />
        {item.industry}
      </div>
      <h3>{item.title}</h3>
    </button>
  );
}
export function Field({
  name,
  label,
  form,
  set,
  options,
  area = false,
  required = false,
  placeholder = "",
  limit = 80,
}) {
  const Tag = area ? "textarea" : "input";
  return (
    <label className="field">
      {label}
      {required && <i> *</i>}
      {options ? (
        <select
          value={form[name] || ""}
          onChange={(e) => set({ ...form, [name]: e.target.value })}
        >
          <option value="">请选择</option>
          {options.map((o) => (
            <option key={o}>{o}</option>
          ))}
        </select>
      ) : (
        <Tag
          required={required}
          maxLength={limit}
          placeholder={placeholder}
          value={form[name] || ""}
          onChange={(e) => set({ ...form, [name]: e.target.value })}
        />
      )}
    </label>
  );
}
