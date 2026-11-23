"""Private COS mirror. Queue changes in the same transaction as publishing the source."""

import fcntl
import os
import time
from urllib.parse import quote

from .store import DATA, db


def destination():
    bucket = os.getenv("TRUPIC_COS_BUCKET")
    if not bucket:
        return None
    region = os.getenv("TRUPIC_COS_REGION")
    if not region or not os.getenv("COS_SECRET_ID") or not os.getenv("COS_SECRET_KEY"):
        raise ValueError("请补齐 COS 地域及服务端凭据。")
    return bucket, region


def client(region):
    from qcloud_cos import CosConfig, CosS3Client

    return CosS3Client(
        CosConfig(
            Region=region,
            SecretId=os.environ["COS_SECRET_ID"],
            SecretKey=os.environ["COS_SECRET_KEY"],
            Token=os.getenv("COS_SECURITY_TOKEN"),
            Scheme="https",
        )
    )


def enqueue(c, folder, names):
    target = destination()
    if not target:
        return
    for name in names:
        path = folder / name
        if path.is_file():
            key = path.relative_to(DATA).as_posix()
            c.execute(
                """INSERT OR IGNORE INTO cos_object(bucket,region,key,action) VALUES(?,?,?,'upload')""",
                (*target, key),
            )


def forget(c, folder):
    prefix = folder.relative_to(DATA).as_posix() + "/"
    c.execute(
        """UPDATE cos_object SET action='delete',due=0 WHERE substr(key,1,?)=?""",
        (len(prefix), prefix),
    )


def drain():
    # The OS releases this lock if the process dies. Pending operations then replay.
    target = destination()
    if not target:
        return 0
    with (DATA / "cos-worker.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        with db() as c:
            entries = c.execute(
                """SELECT * FROM cos_object WHERE bucket=? AND region=? AND action!='ready' AND due<=?
                ORDER BY due,rowid LIMIT 20""",
                (
                    *target,
                    time.time(),
                ),
            ).fetchall()
        for row in entries:
            address = (row["bucket"], row["region"], row["key"], row["action"])
            try:
                api = client(row["region"])
                if row["action"] == "upload":
                    api.upload_file(
                        Bucket=row["bucket"],
                        Key=row["key"],
                        LocalFilePath=str(DATA / row["key"]),
                        ACL="private",
                        EnableMD5=True,
                    )
                    with db(True) as c:
                        c.execute(
                            """UPDATE cos_object SET action='ready',attempts=0,error=NULL
                            WHERE bucket=? AND region=? AND key=? AND action=?""",
                            address,
                        )
                else:
                    api.delete_object(Bucket=row["bucket"], Key=row["key"])
                    with db(True) as c:
                        c.execute(
                            "DELETE FROM cos_object WHERE bucket=? AND region=? AND key=? AND action=?",
                            address,
                        )
            except Exception as exc:
                with db(True) as c:
                    c.execute(
                        """UPDATE cos_object SET attempts=attempts+1,error=?,due=?
                        WHERE bucket=? AND region=? AND key=? AND action=?""",
                        (
                            type(exc).__name__,
                            time.time() + min(3600, 5 * 2 ** min(row["attempts"], 10)),
                            *address,
                        ),
                    )
        return len(entries)


def download_url(c, path, filename):
    target = destination()
    if not target:
        return None
    key = path.relative_to(DATA).as_posix()
    row = c.execute(
        "SELECT action FROM cos_object WHERE bucket=? AND region=? AND key=?",
        (*target, key),
    ).fetchone()
    if not row:
        enqueue(c, path.parent, [path.name])
    if row and row["action"] == "ready":
        return client(target[1]).get_presigned_download_url(
            Bucket=target[0],
            Key=key,
            Expired=300,
            Params={
                "response-content-disposition": "attachment; filename*=UTF-8''"
                + quote(filename, safe="")
            },
            SignHost=True,
        )
