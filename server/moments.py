"""Photo-first Moments copy. Keep merchant facts verbatim across caption choices."""

import re

import numpy as np
from PIL import Image, ImageDraw

from .copy_choices import write_options
from .creative import draft_copy
from .campaign import ROUTES, copy_route
from . import wenan


def round_subject(path):
    """Only substitute an object for a numeral when its actual outline reads as round."""
    with Image.open(path) as photo:
        mask = photo.getchannel("A")
        l, t, r, b = mask.getbbox()
        if not 0.80 <= (r - l) / (b - t) <= 1.25:
            return False
        silhouette = np.asarray(mask.crop((l, t, r, b)).resize((64, 64))) > 128
    ellipse = Image.new("L", (64, 64))
    ImageDraw.Draw(ellipse).ellipse((0, 0, 63, 63), fill=255)
    disk = np.asarray(ellipse) > 0
    return bool((silhouette & disk).sum() / (silhouette | disk).sum() >= 0.85)


def read_photo(plan):
    # Match a category for creative routing, never a price, brand or unseen specification.
    review = plan.get("sourceReview", {})
    detail = review.get("visualDetail", {}).get("label", "")
    for evidence in (plan["moment"]["note"], detail, review.get("reason", "")):
        for route in ROUTES:
            match = re.search(route["match"], evidence, re.I)
            if match:
                plan["subject"] = match.group()
                break
        else:
            continue
        break
    # Emphasise a single unqualified appointment only. Ranges and cutoffs stay verbatim.
    note = plan["moment"]["note"]
    times = list(re.finditer(r"(上午|下午|晚上)\s*(1[0-2]|[1-9])\s*点", note))
    if len(times) == 1 and times[0].group(2) != "12" and not re.search(r"前|后|左右|半|分|截止|取消|至|到\s*\d|点\s*[一二三四五六七八九十0-9]|明天|下周|[~～—-]|不(?:是|在|能)", note):
        period, hour = times[0].groups()
        hour = int(hour) % 12 + (12 if period in ("下午", "晚上") else 0)
        plan["moment"]["clock"] = f"{hour:02d}:00"


def prepare_drafts(spec, tenant):
    """Review candidates once per work. The result page reuses the same reviewed text."""
    plan = spec["plan"]
    moment = plan["moment"]
    local = [draft_copy(plan, variant) for variant in range(3)]
    try:
        reviewed = write_options(spec, tenant)
    except (ValueError, OSError) as exc:
        reviewed = []
        moment["copyFallback"] = str(exc)[:160]
    note = moment["note"]
    candidates = []
    route = copy_route(plan) or {}
    # A model can return its own prompt as a reply, even after approving the line.
    # Prefer a grounded local direction over that placeholder.
    if wenan.social_headline(plan):
        reviewed = [d for d in reviewed if concrete_exchange(d.get("sharingReview", {}))]
        if not note and (scene := route.get("momentDraft")):
            local.insert(0, {**local[0], "title": scene["title"], "caption": scene["caption"], "motif": scene["motif"],
                             "posterDeck": scene.get("deck", ""),
                             "sharingReview": {k: scene[k] for k in ("shareTo", "reply")}})
    invitation = route.get("meetToday")
    if (invitation and moment.get("clock") and "今天" in note and wenan.social_headline(plan)
            and re.search(invitation["match"], note) and not re.search("明天|后天|取消|不要|谢绝|售罄|卖完|休息", note)):
        candidates.append({**local[0], "title": invitation["title"],
                           "sharingReview": {k: invitation[k] for k in ("shareTo", "reply")}})
    seen = set()
    options = []
    for draft in [*candidates, *reviewed, *local]:
        title = draft["title"].strip()
        identity = re.sub(r"[，。！？、,.!?\s]", "", title)
        if not identity or identity in seen:
            continue
        seen.add(identity)
        # A one-line caption is sufficient for a photo. Model-invented descriptions
        # and sales claims must not displace the actual shopkeeper's message.
        caption = draft.get("caption") or title
        if draft in reviewed and draft.get("body") and draft["body"] != title:
            caption = title + "\n" + draft["body"]
        if note:
            caption = note if title in note else title + "\n" + note
        options.append({**draft, "body": caption, "cta": ""})
        if len(options) == 3:
            break
    moment["drafts"] = options


def concrete_exchange(review):
    recipient = review.get("shareTo", "").strip(" 。")
    reply = review.get("reply", "").strip(" 。")
    return bool(recipient and reply and not re.fullmatch(
        r"(?:会?发给|转给|分享给)?(?:我?的)?(?:朋友|顾客|同事|大家|家人|对方|用户)", recipient)
        and not re.search("发给谁|怎么接|怎么回|对方会|接这句话", reply))


def drafts(plan):
    moment = plan["moment"]
    if options := moment.get("drafts"):
        return [{k: draft[k] for k in ("title", "body", "cta")} for draft in options]
    # Saved works created before reviewed draft sets were stored.
    note = moment["note"]
    tone = moment.get("tone", "")
    if note:
        opening = re.split(r"[，,。！？；;\n]", note, maxsplit=1)[0].strip()
        title = opening if 1 < len(opening) <= 16 else "今天的店里"
        invite = "想留一份就给我发消息。" if re.search("预留|预订|能取|可取|多烤|多做", note) else "想问什么，直接给我留言。"
        if re.search("售罄|卖完|订满|约满|不接|不预|谢绝|私信|留言|发消息|联系我|来店里|来看看|来尝|路过|[？?]", note):
            invite = ""
        pairs = [(title, note, invite), ("店里随记", note if invite else "今天店里的一条小记。\n" + note, ""),
                 ("想跟你们分享", "拍张照给你们看看。\n" + note, "")]
    else:
        detail = plan.get("sourceReview", {}).get("visualDetail", {}).get("label")
        observation = ("凑近拍了一张，喜欢这个细节：" + detail + "。") if detail else (
            "今天这张照片里，我最喜欢这一抹" + tone + "。" if tone else "今天在店里拍了张照，给你们看看。"
        )
        pairs = [("今天的随手拍", observation, ""), ("镜头里的今天", "把今天店里的这一幕，留在朋友圈。", ""),
                 ("给你们看看", observation, "你第一眼注意到了哪里？")]
    return [dict(title=title, body=body, cta=cta) for title, body, cta in pairs]


def first_copy(plan):
    return plan["moment"]["drafts"][0].copy()
