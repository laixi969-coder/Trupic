import React, { useState } from "react";
import { api } from "./ui.jsx";

export default function CopyChoices({ quote, value, onChange, disabled }) {
  const [options, setOptions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  async function load() {
    onChange(null);
    setLoading(true);
    setError("");
    try {
      const result = await api("/copy-options", "POST", { quote, previousTitles: options.map(o => o.title) });
      setOptions(result.options);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }
  return <fieldset className="copy-choices" disabled={disabled || loading}>
    <legend>选择海报文案</legend>
    {options.map(option => <label key={option.token}>
      <input type="radio" name="poster-copy" checked={value === option.token}
        onChange={() => onChange({ quote, ...option })} />
      <span><strong>{option.title}</strong>{option.body && <span>{option.body}</span>}{option.cta && <span>{option.cta}</span>}</span>
    </label>)}
    {error && <p role="alert" className="error">{error}</p>}
    <button type="button" className="secondary" onClick={load}>{loading ? "正在写稿和复核…" : options.length ? "换一组文案" : "生成候选文案"}</button>
  </fieldset>;
}
