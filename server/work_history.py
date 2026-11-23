"""Hide completed works immediately, retaining versions for batch undo and accounting."""

from flask import jsonify
from .store import audit, db, ident, now


def hidden(c, work):
    return bool(c.execute("SELECT 1 FROM work_trash WHERE work=?", (work,)).fetchone())


def register(app, services):
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS work_trash(work TEXT PRIMARY KEY, tenant TEXT NOT NULL,
            batch TEXT NOT NULL, created TEXT NOT NULL)""")
        c.execute("CREATE INDEX IF NOT EXISTS trash_batch ON work_trash(tenant,batch)")

    @app.post("/api/works/trash")
    def trash_works():
        t, v = services["reqtenant"](), services["body"]()
        ids = v.get("ids")
        if v.get("all") is not True and (
            not isinstance(ids, list)
            or not ids
            or any(not isinstance(i, str) for i in ids)
        ):
            raise ValueError("请选择需要删除的作品。")
        with db(True) as c:
            if v.get("all") is True:
                ids = [
                    r[0]
                    for r in c.execute(
                        """SELECT id FROM work WHERE tenant=?
                    AND id NOT IN (SELECT work FROM work_trash WHERE tenant=?)""",
                        (t, t),
                    )
                ]
            batch = ident()
            for work in set(ids):
                services["owner"](c, "work", work, t)
                if c.execute(
                    "SELECT 1 FROM job WHERE work=? AND state IN ('running','queued')",
                    (work,),
                ).fetchone():
                    raise ValueError("所选作品正在生成新版本，请完成后再删除。")
                c.execute(
                    "INSERT INTO work_trash VALUES(?,?,?,?)", (work, t, batch, now())
                )
            audit(c, t, "删除历史作品", batch)
        return jsonify(batch=batch, count=len(set(ids)))

    @app.post("/api/works/trash/<batch>/undo")
    def undo_trash(batch):
        t = services["reqtenant"]()
        with db(True) as c:
            n = c.execute(
                "DELETE FROM work_trash WHERE tenant=? AND batch=?", (t, batch)
            ).rowcount
            audit(c, t, "撤销删除历史作品", batch)
        return jsonify(count=n)
