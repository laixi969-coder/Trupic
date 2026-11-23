import CopyChoices from "./CopyChoices.jsx";
import React, { useEffect, useRef, useState } from "react";
import { api, Modal } from "./ui.jsx";

export default function ProductBundle({
  assets,
  refresh,
  fonts = [],
  works = [],
}) {
  const [form, setForm] = useState({
    skill: "launch",
    terms: "",
    sideAsset: "",
    backAsset: "",
    template: "",
    cta: "",
    title: "",
    benefits: "",
    asset: "",
    assetConfirmed: false,
    ratio: "square",
    resolution: 1080,
    dpi: 300,
  });
  const [skills, setSkills] = useState([]);
  const [brand, setBrand] = useState({
    name: "",
    logo: "",
    color: "#315744",
    font: "",
  });
  const [brandStatus, setBrandStatus] = useState("");
  const [packs, setPacks] = useState([]);
  const [chosenCopy, setChosenCopy] = useState(null);
  const [quote, setQuote] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [zoom, setZoom] = useState(null);
  const requestKey = useRef("");
  const lastProgress = useRef(null);
  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;
  const selected = assets.find((a) => a.id === form.asset);
  useEffect(() => {
    let active = true;
    Promise.all([api("/creative-skills"), api("/brand-kit")])
      .then(([catalog, kit]) => {
        if (active) {
          setSkills(catalog);
          setBrand(kit);
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, []);
  useEffect(() => {
    let active = true;
    let timer;
    async function poll() {
      try {
        const rows = await api("/bundles");
        if (active) {
          setPacks(rows);
          const progress = rows
            .flatMap((pack) => pack.items.map((item) => item.job + item.state))
            .join();
          if (
            lastProgress.current !== null &&
            lastProgress.current !== progress
          ) {
            await refreshRef.current();
          }
          lastProgress.current = progress;
        }
      } catch (e) {
        if (active) setError(e.message);
      }
      if (active) timer = setTimeout(poll, 3000);
    }
    poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, []);
  function patch(changes) {
    setForm((f) => ({ ...f, ...changes }));
    setQuote(null);
  }
  async function perform(fn) {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function upload(e) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    await perform(async () => {
      const data = new FormData();
      data.append("image", file);
      const asset = await api("/assets", "POST", data);
      await refresh();
      patch({ asset: asset.id, assetConfirmed: false });
    });
  }
  async function preview(e) {
    e.preventDefault();
    await perform(async () => {
      setQuote(await api("/bundles/preview", "POST", form));
      requestKey.current = crypto.randomUUID();
    });
  }
  async function create() {
    await perform(async () => {
      const pack = await api("/bundles", "POST", {
        quote: quote.quote,
        copyChoice: chosenCopy?.quote === quote.quote ? chosenCopy.token : "",
        confirmed: true,
        confirmedCost: quote.cost,
        requestKey: requestKey.current,
      });
      setPacks((rows) => [pack, ...rows.filter((r) => r.id !== pack.id)]);
      setQuote(null);
      await refresh();
    });
  }
  async function retry(job) {
    await perform(async () => {
      await api("/jobs/" + job + "/retry", "POST", {});
      setPacks(await api("/bundles"));
    });
  }
  const states = {
    queued: "等待制作",
    running: "制作中",
    failed: "制作失败",
    complete: "已完成",
  };
  return (
    <section className="bundle-page">
      <h1>成套素材</h1>
      <div className="skill-grid">
        {skills.map((skill) => (
          <button
            key={skill.id}
            className={
              form.skill === skill.id ? "skill-choice selected" : "skill-choice"
            }
            aria-pressed={form.skill === skill.id}
            onClick={() => patch({ skill: skill.id })}
          >
            <strong>{skill.name}</strong>
            <span>{skill.description}</span>
          </button>
        ))}
      </div>
      <details
        className="brand-kit"
        open={form.skill === "brand" ? true : undefined}
      >
        <summary>品牌规范</summary>
        <label>
          品牌名称
          <input
            value={brand.name}
            onChange={(e) => setBrand({ ...brand, name: e.target.value })}
          />
        </label>
        <label>
          品牌色
          <input
            type="color"
            value={brand.color}
            onChange={(e) => setBrand({ ...brand, color: e.target.value })}
          />
        </label>
        <label>
          Logo
          <select
            value={brand.logo}
            onChange={(e) => setBrand({ ...brand, logo: e.target.value })}
          >
            <option value="">选择素材库里的 Logo</option>
            {assets.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          字体
          <select
            value={brand.font}
            onChange={(e) => setBrand({ ...brand, font: e.target.value })}
          >
            <option value="">内置字体</option>
            {fonts.map((f) => (
              <option key={f.id} value={f.id}>
                {f.name}
              </option>
            ))}
          </select>
        </label>
        <button
          className="secondary"
          disabled={busy}
          onClick={() =>
            perform(async () => {
              setBrand(await api("/brand-kit", "POST", brand));
              setQuote(null);
              setBrandStatus("品牌规范已保存，后续素材会复用。");
            })
          }
        >
          保存品牌规范
        </button>
        <p role="status">{brandStatus}</p>
      </details>
      <h2>{skills.find((s) => s.id === form.skill)?.name || "商品上新"}</h2>
      <form className="bundle-form" onSubmit={preview}>
        <label>
          {form.skill === "brand" || form.skill === "mockup"
            ? "品牌名称"
            : "商品 / 活动名称"}
          <input
            required
            maxLength={60}
            value={form.title}
            onChange={(e) => patch({ title: e.target.value })}
          />
        </label>
        <label>
          {form.skill === "live"
            ? "开播时间与直播内容"
            : "已确认的卖点 / 活动信息"}
          <textarea
            required
            maxLength={200}
            value={form.benefits}
            placeholder="填写材质、规格或使用特点，按实际商品描述"
            onChange={(e) => patch({ benefits: e.target.value })}
          />
        </label>
        <label>
          {form.skill === "mockup" || form.skill === "brand"
            ? "Logo 图片"
            : form.skill === "angles"
              ? "正面照片"
              : "商品照片"}
          <select
            required
            value={form.asset}
            onChange={(e) =>
              patch({ asset: e.target.value, assetConfirmed: false })
            }
          >
            <option value="">请选择素材库里的商品照片</option>
            {assets.map((a) => (
              <option key={a.id} value={a.id} disabled={a.risk}>
                {a.name}
                {a.risk ? "（请更换清晰照片）" : ""}
              </option>
            ))}
          </select>
        </label>
        {form.skill === "promotion" && (
          <label>
            有效期及适用条件
            <textarea
              required
              maxLength={150}
              value={form.terms}
              onChange={(e) => patch({ terms: e.target.value })}
            />
          </label>
        )}
        {form.skill === "social" && (
          <label>
            收尾页标题
            <input
              maxLength={60}
              value={form.cta}
              placeholder="例如 查看规格与选购方式"
              onChange={(e) => patch({ cta: e.target.value })}
            />
          </label>
        )}
        {form.skill === "angles" &&
          ["sideAsset", "backAsset"].map((field, i) => (
            <label key={field}>
              {i === 0 ? "侧面照片" : "背面照片"}
              <select
                required
                value={form[field]}
                onChange={(e) => patch({ [field]: e.target.value })}
              >
                <option value="">选择该角度的实拍</option>
                {assets
                  .filter((a) => !a.risk)
                  .map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
              </select>
            </label>
          ))}
        {form.skill === "remake" && (
          <label>
            参考短片
            <select
              required
              value={form.template}
              onChange={(e) => patch({ template: e.target.value })}
            >
              <option value="">选择已有 Trupic 九秒短片</option>
              {works
                .filter((w) => w.kind === "video")
                .map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.title}
                  </option>
                ))}
            </select>
          </label>
        )}
        <label>
          上传商品或 Logo 图片
          <input
            type="file"
            accept="image/jpeg,image/png,image/webp"
            disabled={busy}
            onChange={upload}
          />
        </label>
        {selected && (
          <div className="bundle-source">
            <img src={selected.url} alt="核对商品主体" />
            <label>
              <input
                type="checkbox"
                checked={form.assetConfirmed}
                onChange={(e) => patch({ assetConfirmed: e.target.checked })}
              />
              已核对商品轮廓与标识完整
            </label>
          </div>
        )}
        <label>
          画幅
          <select
            value={form.ratio}
            onChange={(e) => patch({ ratio: e.target.value })}
          >
            <option value="square">方形 1:1</option>
            <option value="portrait">竖版 3:4</option>
            <option value="feed">信息流 4:5</option>
          </select>
        </label>
        <button className="primary" disabled={busy || !form.assetConfirmed}>
          查看交付方案
        </button>
      </form>
      {error && (
        <p role="alert" className="bundle-error">
          {error}
        </p>
      )}
      {quote && (
        <section className="bundle-quote">
          <h2>{quote.title}</h2>
          <p>
            {quote.roles.join(" · ")}，共 {quote.roles.length} 项
          </p>
          <p>{quote.note}</p>
          <p>整套 {quote.cost} 积分，每项成功交付后结算。</p>
          {quote.requiresCopyChoice && <CopyChoices key={quote.quote} quote={quote.quote} value={chosenCopy?.quote === quote.quote ? chosenCopy.token : ""} onChange={setChosenCopy} disabled={busy} />}
          <button className="primary" disabled={busy || (quote.requiresCopyChoice && chosenCopy?.quote !== quote.quote)} onClick={create}>
            确认并生成整套
          </button>
        </section>
      )}
      {packs.map((pack) => (
        <section className="bundle-pack" key={pack.id}>
          <div className="bundle-heading">
            <h2>
              {pack.skillName || "商品上新"} · {pack.title}
            </h2>
            {pack.complete ? (
              <a className="primary" href={pack.download} download>
                整套下载 ZIP
              </a>
            ) : (
              <span>
                {pack.items.filter((i) => i.state === "complete").length} /{" "}
                {pack.items.length} 项完成
              </span>
            )}
          </div>
          <div className="bundle-grid">
            {pack.items.map((item) => (
              <article className="bundle-card" key={item.job}>
                {item.preview ? (
                  <button
                    className="bundle-image"
                    onClick={() => setZoom(item)}
                    aria-label={"预览" + item.label}
                  >
                    <img src={item.preview} alt={item.label} />
                  </button>
                ) : (
                  <div className="bundle-placeholder" role="status">
                    {states[item.state]}
                  </div>
                )}
                <h3>{item.label}</h3>
                <p>{states[item.state]}</p>
                {item.error && <p role="alert">{item.error}</p>}
                {item.download && (
                  <a href={item.download} download>
                    下载此项
                  </a>
                )}
                {item.state === "failed" && (
                  <button
                    className="secondary"
                    disabled={busy}
                    onClick={() => retry(item.job)}
                  >
                    重试此项
                  </button>
                )}
              </article>
            ))}
          </div>
        </section>
      ))}
      {zoom && (
        <Modal title={zoom.label} onClose={() => setZoom(null)}>
          {zoom.video ? (
            <video className="bundle-zoom" controls src={zoom.video} />
          ) : (
            <img className="bundle-zoom" src={zoom.preview} alt={zoom.label} />
          )}
          <a href={zoom.download} download>
            下载此项
          </a>
        </Modal>
      )}
    </section>
  );
}
