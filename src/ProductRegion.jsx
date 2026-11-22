import React, { useState } from "react";

export default function ProductRegion({ asset, region, change, detail = false, children }) {
  const [editing, setEditing] = useState(false);
  const [corner, setCorner] = useState(null);
  function point(e) {
    const box = e.currentTarget.getBoundingClientRect();
    const x = (e.clientX - box.left) / box.width,
      y = (e.clientY - box.top) / box.height;
    if (!corner) {
      setCorner([x, y]);
      return;
    }
    const next = [
      Math.min(x, corner[0]),
      Math.min(y, corner[1]),
      Math.max(x, corner[0]),
      Math.max(y, corner[1]),
    ];
    if (next[0] === next[2] || next[1] === next[3]) return;
    change(next);
    setCorner(null);
    setEditing(false);
  }
  return (
    <div className="region-field">
      <button
        className="secondary"
        type="button"
        onClick={() => {
          setEditing(!editing);
          setCorner(null);
        }}
      >
        {editing
          ? "关闭标注"
          : region
            ? (detail ? "重新框选中镜细节" : "重新标注原图区域")
            : (detail ? "指定短片中镜的细节（选填）" : "标注需保真的标识或包装文字")}
      </button>
      {region && (
        <button
          type="button"
          className="textbtn"
          onClick={() => {
            change(null);
            setCorner(null);
          }}
        >
          清除选区
        </button>
      )}
      {(editing || region) && (
        <>
          <p>
            {editing
              ? corner
                ? "再点选区的对角。"
                : (detail ? "在原图上框住一个能看清的商品细节。" : "在原图上点选标识的一角。")
              : (detail ? "第 3–6 秒会推近框内的细节。" : "请确认框内文字或标识清晰、无遮挡。")}
          </p>
          <div className="region-stage" onClick={editing ? point : undefined}>
            <img src={asset.original} draggable="false" alt="商品原图标注" />
            {region && (
              <span
                style={{
                  left: region[0] * 100 + "%",
                  top: region[1] * 100 + "%",
                  width: (region[2] - region[0]) * 100 + "%",
                  height: (region[3] - region[1]) * 100 + "%",
                }}
              />
            )}
            {corner && (
              <i
                style={{
                  left: corner[0] * 100 + "%",
                  top: corner[1] * 100 + "%",
                }}
              />
            )}
          </div>
          {region && children}
        </>
      )}
    </div>
  );
}
