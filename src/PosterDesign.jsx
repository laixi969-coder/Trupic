import React, { useRef, useState, useId } from "react";
import { Upload, Check, ArrowUpRight } from "lucide-react";
import { api } from "./ui.jsx";

export function FontPicker({
  fonts,
  value,
  onChange,
  onRefresh,
  profile = false,
  defaultFont = "",
}) {
  const input = useRef(null),
    id = useId();
  const [busy, setBusy] = useState(false),
    [message, setMessage] = useState("");
  async function upload(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setBusy(true);
    setMessage("");
    try {
      if (file.size > 32 * 1024 * 1024)
        throw new Error("单款字体最大为 32 MB。");
      const form = new FormData();
      form.append("font", file);
      const font = await api("/fonts", "POST", form);
      await onRefresh();
      onChange(font.id);
      setMessage(
        "已载入 " + font.name + "，可用字形映射 " + font.glyphs + " 个。",
      );
    } catch (err) {
      setMessage(err.message);
    } finally {
      setBusy(false);
    }
  }
  const chosen = fonts.find(
    (f) => f.id === (value === "profile" ? defaultFont : value),
  );
  return (
    <div className={"font-picker " + (profile ? "profile-font" : "")}>
      <label htmlFor={id}>{profile ? "工作室默认字体" : "成品字体"}</label>
      <div className="font-controls">
        <select
          id={id}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        >
          {!profile && <option value="profile">跟随商家档案</option>}
          <option value={profile ? "" : "builtin"}>按版式配字</option>
          {fonts.map((f) => (
            <option key={f.id} value={f.id}>
              {f.name}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="toolbtn"
          disabled={busy}
          onClick={() => input.current?.click()}
        >
          <Upload size={14} />
          {busy ? "正在读取" : "导入字体"}
        </button>
      </div>
      <input
        ref={input}
        type="file"
        aria-label="上传品牌字体"
        hidden
        accept=".ttf,.otf"
        onChange={upload}
      />
      {chosen && (
        <img
          className="font-specimen"
          alt={chosen.name + " 中英文与价格试排"}
          src={"/api/fonts/" + chosen.id + "/sample.png"}
        />
      )}
      <small role="status">
        {message || "可导入有商用授权的 TTF / OTF，包括 Hunter 导出的字体。"}
      </small>
    </div>
  );
}

export function StyleGallery({ styles, onChoose }) {
  return (
    <div className="design-gallery">
      {styles.map((s) => (
        <button type="button" key={s.id} onClick={() => onChoose(s)}>
          <img
            loading="lazy"
            src={"/designs/" + s.id + ".webp"}
            alt={s.name + "实排样张"}
          />
          <span>
            {s.name}
            <ArrowUpRight size={15} />
          </span>
        </button>
      ))}
    </div>
  );
}

export function IndustryGallery({ examples, onChoose }) {
  return (
    <div className="industry-gallery">
      {examples.map((s) => (
        <article key={s.id}>
          <img
            src={"/designs/industry-" + s.id + ".webp"}
            alt={s.name + "海报《" + s.title + "》"}
            loading="lazy"
          />
          <h3>
            {s.name} · {s.title}
          </h3>
          <p>{s.shot}</p>
          <details>
            <summary>用色与排版</summary>
            <div className="industry-colors">
              {s.colors.map((c) => (
                <span
                  key={c}
                  style={{ backgroundColor: c }}
                  title={c}
                  aria-label={c}
                />
              ))}
            </div>
            <p>{s.type}</p>
            <p>{s.focus}</p>
          </details>
          <button type="button" className="textbtn" onClick={() => onChoose(s)}>
            采用{s.name}构图 <ArrowUpRight size={15} />
          </button>
        </article>
      ))}
    </div>
  );
}

export function PosterOptions({ draft, patch, data, refresh }) {
  const selected = data.posterStyles.find((s) => s.id === draft.posterStyle);
  return (
    <div className="design-options">
      <div className="design-option-head">
        <label htmlFor="design-select">海报版式</label>
        <select
          id="design-select"
          value={draft.posterStyle}
          onChange={(e) => patch({ posterStyle: e.target.value })}
        >
          <option value="auto">智能推荐</option>
          {data.posterStyles.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </div>
      <div className="design-option-head">
        <label htmlFor="lettering-select">图形文字</label>
        <select
          id="lettering-select"
          value={draft.lettering}
          onChange={(e) => patch({ lettering: e.target.value })}
        >
          {Object.entries({
            auto: "随构图搭配",
            both: "中英文组合",
            han: "中文大字",
            latin: "英文造型字",
            off: "关闭装饰字",
          }).map(([id, label]) => (
            <option key={id} value={id}>
              {label}
            </option>
          ))}
        </select>
      </div>
      <div className="design-thumbs">
        {data.posterStyles.map((s) => (
          <button
            type="button"
            key={s.id}
            aria-pressed={selected?.id === s.id}
            onClick={() => patch({ posterStyle: s.id })}
          >
            <img src={"/designs/" + s.id + ".webp"} alt="" />
            <span>
              {s.name}
              {selected?.id === s.id && <Check size={13} />}
            </span>
          </button>
        ))}
      </div>
      {selected && <p>{selected.intent}</p>}
      <div className="design-controls">
        <FontPicker
          defaultFont={data.profile.brandFont}
          fonts={data.fonts}
          value={draft.fontId}
          onChange={(fontId) => patch({ fontId })}
          onRefresh={refresh}
        />
      </div>
    </div>
  );
}

export function ExportOptions({ draft, patch, ratios }) {
  const video = draft.kind === "video";
  const ratioKey = video ? "videoRatio" : "ratio",
    resolutionKey = video ? "videoResolution" : "resolution";
  const ratio = draft[ratioKey],
    res = draft[resolutionKey];
  const [a, b] = ratios[ratio].split(" ").at(-1).split(":").map(Number);
  const unit = res / Math.min(a, b);
  return (
    <div className="export-options">
      <label>
        画幅
        <select
          aria-label={video ? "短片画幅" : "海报画幅"}
          value={ratio}
          onChange={(e) => patch({ [ratioKey]: e.target.value })}
        >
          {Object.entries(ratios).map(([key, name]) => (
            <option key={key} value={key}>
              {name}
            </option>
          ))}
        </select>
      </label>
      <label>
        分辨率
        <select
          aria-label="导出分辨率"
          value={res}
          onChange={(e) => patch({ [resolutionKey]: Number(e.target.value) })}
        >
          {[720, 1080, 2160].map((n) => (
            <option key={n} value={n}>
              {n} {video ? "p" : "px 短边"}
            </option>
          ))}
        </select>
      </label>
      {!video && (
        <label>
          印刷精度
          <select
            aria-label="印刷精度"
            value={draft.dpi}
            onChange={(e) => patch({ dpi: Number(e.target.value) })}
          >
            {[72, 150, 300].map((n) => (
              <option key={n} value={n}>
                {n} DPI
              </option>
            ))}
          </select>
        </label>
      )}
      <small aria-live="polite">
        {Math.round(a * unit)} × {Math.round(b * unit)} ·{" "}
        {video ? "MP4 / 24 fps" : "PNG"}
      </small>
    </div>
  );
}
