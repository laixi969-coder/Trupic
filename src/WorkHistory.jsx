import React, { useState } from "react";
import { api } from "./ui.jsx";

export default function WorkHistory({ works, total, refresh, renderCard }) {
  const [selected, select] = useState([]);
  const [undo, setUndo] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function change(payload) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      if (payload) {
        const r = await api("/works/trash", "POST", payload);
        setUndo(r.batch);
      } else {
        await api("/works/trash/" + undo + "/undo", "POST", {});
        setUndo("");
      }
      select([]);
      await refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="history-actions">
        {selected.length > 0 && (
          <button
            className="secondary"
            disabled={busy}
            onClick={() => change({ ids: selected })}
          >
            删除选中（{selected.length}）
          </button>
        )}
        {total > 0 && (
          <button
            className="textbtn"
            disabled={busy}
            onClick={() => change({ all: true })}
          >
            删除全部作品
          </button>
        )}
        {undo && (
          <button
            className="secondary"
            disabled={busy}
            onClick={() => change(null)}
          >
            撤销上次删除
          </button>
        )}
      </div>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <div className="workgrid">
        {works.map((w) => (
          <article key={w.id}>
            {renderCard(w)}
            <div className="history-actions">
              <label>
                <input
                  type="checkbox"
                  checked={selected.includes(w.id)}
                  onChange={(e) =>
                    select((ids) =>
                      e.target.checked
                        ? [...ids, w.id]
                        : ids.filter((id) => id !== w.id),
                    )
                  }
                />{" "}
                选择
              </label>
              <button
                className="textbtn"
                disabled={busy}
                onClick={() => change({ ids: [w.id] })}
              >
                删除
              </button>
            </div>
          </article>
        ))}
      </div>
    </>
  );
}
