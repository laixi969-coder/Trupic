import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from .creative import RISK, UNKNOWN, prepare, uidnum
from .model import settings
from .store import audit, db, ident, now


def active_rule(c, tenant):
    for row in c.execute(
        "SELECT * FROM rules WHERE status IN ('live','pilot') ORDER BY (status='pilot') DESC,created DESC,rowid DESC"
    ):
        if row["status"] == "live" or uidnum(tenant) % 100 < row["percent"]:
            return dict(row)
    return dict(id="baseline", name="创意策略 v1", method="moment")


# Business intent can transfer between industries and media.
INTENTS = (
    ("新客", "首次到店", "第一次来", "初次体验", "拉新"),
    ("老客", "老顾客", "复购", "回头客", "再次到店"),
    ("上新", "新品", "新款", "新口味", "上市"),
    ("预约", "预订", "订位", "订座"),
    ("聚餐", "组局", "相聚", "聚会"),
    ("午休", "午间", "午餐时间"),
    ("特写", "微距", "近景", "放大细节"),
)


def retrieve_method(c, brief, profile):
    context = " ".join(
        [brief, *(profile.get(k, "") for k in ("product", "industry", "audience"))]
    ).casefold()
    best = None
    best_score = 0
    for row in c.execute("""SELECT r.id rule,c.id,c.title,c.kind,c.source,c.license,c.lesson,c.scenario,c.tags,r.method
            FROM rules r JOIN cases c ON c.id=r.case_id WHERE r.retrievable=1
            AND c.status='approved' AND c.category!='反面案例' ORDER BY r.created DESC,r.rowid DESC"""):
        terms = {
            s.casefold()
            for s in re.split(r"[，、,；;\s/]+", row["tags"] + " " + row["scenario"])
            if len(s) >= 2
        }
        matched = sorted(s for s in terms if s in context)
        related = [word for word in sorted(terms - set(matched))
                   if any(word in group and any(alias in context for alias in group) for group in INTENTS)]
        score = 2 * sum(len(s) for s in matched) + sum(len(s) for s in related)
        matched.extend(related)
        if score > best_score:
            best_score = score
            best = {**dict(row), "matched": matched}
    return best


def extracted_method(title, summary=""):
    text = title + " " + summary
    for words, method in [
        (
            "close.up|macro|细节|特写",
            "放大一个能从原素材核实的细节，用标题说清它与顾客的关系。",
        ),
        (
            "before|after|前后|过程",
            "用同一视角组织前后两幕，让顾客跟随变化，避免补造实际效果。",
        ),
        (
            "color|colour|palette|色彩|配色",
            "从商品原图取主色，缩减背景色，使标题与主体形成可读对比。",
        ),
        (
            "film|video|短片|镜头",
            "用前三秒提出一个可见的问题，中段展示过程，结尾给出具体行动。",
        ),
        (
            "weekend|friend|周末|好友",
            "以一个具体聚会时刻带出需求，用可执行的邀请结尾。",
        ),
    ]:
        if re.search(words, text, re.I):
            return method
    return "候选方法：从标题中提炼消费场景，核对原作中画面与文案的呼应后再入库。"


def run_tests(rule):
    output = []
    baseline = {"name": "初始对照", "method": "moment", "id": "baseline"}
    for name, brief, subject in [
        ("台球好友相聚", "宣传台球室，周末和朋友组局", "台球"),
        ("火锅老客", "给火锅老客发一份邀请", "火锅"),
        ("茶饮上新", "为奶茶做一张上新海报", "饮品"),
        ("护理知识", "美容院日常护理知识分享", "日常护理"),
    ]:
        p = prepare(brief, {}, [], rule)
        output.append(dict(name=name, ok=p["subject"] == subject and bool(p["angle"]),
                           sample=p["angle"], baseline=prepare(brief, {}, [], baseline)["angle"]))
    try:
        prepare("编造优惠价格", {}, [], rule)
        blocked = False
    except ValueError:
        blocked = True
    output.append(
        dict(name="未确认事实前置拦截", ok=blocked, sample="测试未确认折扣的处理")
    )
    if rule.get("lesson"):
        lesson = rule["lesson"]
        output.append(
            dict(
                name="关联方法真实性门槛",
                ok=not (RISK.search(lesson) or UNKNOWN.search(lesson)),
                sample=lesson,
            )
        )
    return output


def reference_kind(node):
    types = [e.get("type", "") for e in node.iter()]
    if any(t.startswith("video/") for t in types):
        return "视频"
    if any(t.startswith("image/") for t in types):
        return "图片"
    title = node.findtext("{*}title") or ""
    if re.search(r"视频|短片|镜头|video|film", title, re.I):
        return "视频"
    return "图片" if re.search(r"海报|摄影|构图|配色|poster|photo|design", title, re.I) else "文案"


def discover_feed():
    # Sources are operator-configured feeds with explicit use conditions; only metadata is retained.
    cfg = settings()
    url = cfg["feed"]
    license = cfg["license"]
    if not (url.startswith("https://") and license):
        raise ValueError("请先配置已获授权的 HTTPS 订阅源和引用条件。")
    req = urllib.request.Request(
        url, headers={"User-Agent": "TrupicReferenceReader/1.0"}
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        data = r.read(1_048_577)
    if len(data) > 1_048_576 or b"<!DOCTYPE" in data.upper():
        raise ValueError("源文件超出可读取范围。")
    root = ET.fromstring(data)
    entries = root.findall(".//item") + root.findall(".//{*}entry")
    added = 0
    with db(True) as c:
        for node in entries[:16]:
            title = (node.findtext("{*}title") or "").strip()
            link = next((link for link in node.findall("{*}link") if link.get("rel", "alternate") == "alternate"), None)
            source = (
                (link.text or link.get("href", "")).strip() if link is not None else ""
            )
            if not title or urllib.parse.urlparse(source).scheme not in (
                "https",
                "http",
            ):
                continue
            cur = c.execute(
                "INSERT OR IGNORE INTO cases(id,title,source,license,kind,category,lesson,issue,status,created) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    ident(),
                    title[:150],
                    source[:1000],
                    license[:200],
                    reference_kind(node),
                    "优秀案例",
                    extracted_method(title, node.findtext("{*}description") or ""),
                    "",
                    "pending",
                    now(),
                ),
            )
            added += cur.rowcount
        audit(c, "system", "发现参考案例", str(added))
    return added


def validate_pinterest_settings(cfg):
    board = cfg["board"]
    if board and not re.fullmatch(r"[0-9]+", board):
        raise ValueError("Pinterest 画板 ID 应为数字。")
    if board and cfg["pinToken"] and not cfg["pinRights"]:
        raise ValueError("启用 Pinterest 画板同步前，请填写画板内容的引用条件。")


def discover():
    cfg = settings()
    entries = []
    if cfg["board"] and cfg["pinToken"] and cfg["pinRights"]:
        board = cfg["board"]
        if not re.fullmatch(r"[0-9]+", board):
            raise ValueError("Pinterest 画板 ID 应为数字。")
        req = urllib.request.Request(
            f"https://api.pinterest.com/v5/boards/{board}/pins?page_size=25",
            headers={"Authorization": "Bearer " + cfg["pinToken"]},
        )
        try:
            with urllib.request.urlopen(req, timeout=12) as r:
                pins = json.load(r).get("items", [])
        except (OSError, ValueError) as e:
            raise ValueError("Pinterest 未返回画板内容，请核对授权与画板 ID。") from e
        for p in pins:
            if str(p.get("id", "")).isdigit():
                entries.append(
                    (
                        ident(),
                        str(p.get("title") or "画板视觉参考")[:150],
                        "https://www.pinterest.com/pin/" + str(p["id"]) + "/",
                        cfg["pinRights"][:220],
                        "图片",
                        "优秀案例",
                        extracted_method(
                            str(p.get("title") or ""), str(p.get("description") or "")
                        ),
                        "",
                        "pending",
                        now(),
                    )
                )
    added = 0
    if cfg["feed"] and cfg["license"]:
        try:
            added = discover_feed()
        except (OSError, ET.ParseError) as e:
            raise ValueError("暂时无法读取订阅源，请核对地址或稍后重试。") from e
    elif not cfg["board"]:
        raise ValueError("请先配置已授权的订阅源或 Pinterest 画板。")
    with db(True) as c:
        for entry in entries:
            added += c.execute(
                "INSERT OR IGNORE INTO cases(id,title,source,license,kind,category,lesson,issue,status,created) VALUES(?,?,?,?,?,?,?,?,?,?)",
                entry,
            ).rowcount
        if entries:
            audit(c, "system", "Pinterest 画板同步", str(len(entries)))
    return added
