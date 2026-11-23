import React, { useRef, useState } from "react";
import { api, Busy } from "./ui.jsx";

export default function CopyChoices({ quote, value, onChange, disabled, confirmCost, submitting, onReplan }) {
  const [options, setOptions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const inFlight = useRef(false);
  async function load() {
    if (inFlight.current) return;
    inFlight.current = true;
    setLoading(true);
    setError("");
    try {
      const result = await api("/copy-options", "POST", { quote, previousTitles: options.map(o => o.title) });
      setOptions(result.options);
      onChange(null);
    } catch (e) {
      setError(e.message);
    } finally {
      inFlight.current = false;
      setLoading(false);
    }
  }
  return <fieldset className="copy-choices" disabled={disabled || loading}>
    <legend>{options.length ? "选择一组文案制作海报" : "先选文案，再制作海报"}</legend>
    {options.map(option => <label key={option.token}>
      <input type="radio" name="poster-copy" checked={value === option.token}
        onChange={() => onChange({ quote, ...option })} />
      <span><strong>{option.title}</strong>{option.body && <span>{option.body}</span>}{option.cta && <span>{option.cta}</span>}</span>
    </label>)}
    {error && <p role="alert" className="error">{error} {onReplan && error.includes("过期") &&
      <button type="button" className="textbtn" onClick={onReplan}>重新检查需求</button>}</p>}
    <div className="copy-actions">
      <button type="button" className={options.length ? "secondary" : "primary"} onClick={load}>
        {loading ? <Busy text="正在写稿和复核…" /> : options.length ? "换一组文案" : "生成 2–3 组候选文案"}
      </button>
      {options.length > 0 && confirmCost != null && <button type="submit" className="primary" disabled={!value}>
        {submitting ? <Busy text="正在提交海报" /> : "确认文案并制作海报 · " + confirmCost + " 积分"}
      </button>}
    </div>
    {loading && <p role="status">正在根据需求和素材拟稿，通过复核后会在这里显示。</p>}
  </fieldset>;
}
