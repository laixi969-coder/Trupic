import React, { useState } from "react";
const industries = [
  "茶饮咖啡",
  "餐饮火锅",
  "烘焙甜品",
  "休闲娱乐",
  "美容护理",
  "诊所",
  "健身运动",
  "零售服务",
  "生活用品",
  "其他",
];
export default function IndustryPicker({ profile, setProfile }) {
  const [custom, setCustom] = useState("");
  const selected =
    profile.industryTags ||
    (profile.industry || "").split("、").filter(Boolean);
  const change = (tags) =>
    setProfile({ ...profile, industryTags: tags, industry: tags.join("、") });
  function add() {
    const name = custom.trim();
    if (name && !selected.includes(name) && selected.length < 10) {
      change([...selected, name]);
      setCustom("");
    }
  }
  return (
    <fieldset className="spec-picker industry-picker">
      <legend>经营行业（可多选）</legend>
      <div className="industry-tags">
        {[...new Set([...industries, ...selected])].map((name) => (
          <button
            type="button"
            key={name}
            aria-pressed={selected.includes(name)}
            disabled={!selected.includes(name) && selected.length >= 10}
            onClick={() =>
              change(
                selected.includes(name)
                  ? selected.filter((n) => n !== name)
                  : [...selected, name],
              )
            }
          >
            {name}
          </button>
        ))}
      </div>
      <div className="industry-custom">
        <label className="field">
          自定义行业
          <input
            value={custom}
            maxLength={24}
            onChange={(e) => setCustom(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                add();
              }
            }}
          />
        </label>
        <button
          type="button"
          disabled={!custom.trim() || selected.length >= 10}
          onClick={add}
        >
          添加
        </button>
      </div>
    </fieldset>
  );
}
