import React from "react";

export const shapes = {
  square: "1:1",
  portrait: "3:4",
  story: "9:16",
  landscape: "16:9",
  feed: "4:5",
};

export function RatioPicker({ value, onChange }) {
  return (
    <fieldset className="spec-picker">
      <legend>画幅</legend>
      {Object.entries(shapes).map(([key, label]) => {
        const [w, h] = label.split(":").map(Number);
        return (
          <button
            key={key}
            type="button"
            aria-pressed={value === key}
            onClick={() => onChange(key)}
          >
            <i
              aria-hidden="true"
              style={{
                width: (20 * w) / Math.max(w, h),
                height: (20 * h) / Math.max(w, h),
              }}
            />
            {label}
          </button>
        );
      })}
    </fieldset>
  );
}

export default function CreationSpecs({
  draft,
  patch,
  prices,
  profile,
  durations,
}) {
  const video = draft.kind === "video";
  return (
    <>
      <div className="creation-modes">
        {[
          ["poster", "图片文字一键"],
          ["video", "视频文字一键"],
        ].map(([kind, label]) => (
          <button
            key={kind}
            type="button"
            aria-pressed={kind === draft.kind}
            onClick={() => patch({ kind })}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="creation-specs">
        <RatioPicker
          value={video ? draft.videoRatio : draft.ratio}
          onChange={(ratio) => patch(video ? { videoRatio: ratio } : { ratio })}
        />
        {video && (
          <fieldset className="spec-picker">
            <legend>短片时长</legend>
            {durations.map((n) => (
              <button
                key={n}
                type="button"
                aria-pressed={
                  (durations.includes(draft.duration) ? draft.duration : 15) ===
                  n
                }
                onClick={() => patch({ duration: n })}
              >
                {n} 秒
              </button>
            ))}
          </fieldset>
        )}
        {!video && (
          <fieldset className="spec-picker">
            <legend>图片数量</legend>
            {[1, 2].map((n) => (
              <button
                key={n}
                type="button"
                aria-pressed={(draft.imageCount || 1) === n}
                onClick={() => patch({ imageCount: n })}
              >
                {n} 张 · {prices.copy + prices.poster * n} 积分
              </button>
            ))}
          </fieldset>
        )}
      </div>
      <details className="brief-facts">
        <summary>宣传用途与商品 · {profile.industry || "选择行业"}</summary>
        <a href="#profile">修改经营行业</a>
        <label className="field">
          宣传用途
          <select
            value={draft.businessGoal || ""}
            onChange={(e) => patch({ businessGoal: e.target.value })}
          >
            <option value="">根据需求判断</option>
            {[
              "日常分享",
              "活动宣传",
              "吸引新客",
              "新品上市",
              "具体菜品或服务",
            ].map((v) => (
              <option key={v}>{v}</option>
            ))}
          </select>
        </label>
        <label className="field">
          本次宣传的商品或服务
          <input
            value={draft.promotedItem || ""}
            maxLength={80}
            onChange={(e) => patch({ promotedItem: e.target.value })}
          />
        </label>
      </details>
    </>
  );
}
