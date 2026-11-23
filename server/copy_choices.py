"""Reviewed poster copy, bound to the merchant's signed production quote."""

import hashlib
import json
import os
import re
from difflib import SequenceMatcher
from pathlib import Path

from flask import abort
from itsdangerous import BadSignature

from . import model, wenan
from .campaign import LOCKED
from .creative import copy_inputs, unsupported_copy
from .store import DATA
from .visual_review import compact_local_vision, preflight, source_images


def proposal_specs(quote):
    if quote.get("autoCreation"):
        return [item["spec"] for item in quote["items"]]
    if quote.get("bundle"):
        return quote["specs"]
    return [quote["spec"]]


def _quote_id(token):
    return hashlib.sha256(token.encode()).hexdigest()


def object_schema(**fields):
    return {
        "type": "object",
        "properties": fields,
        "required": list(fields),
        "additionalProperties": False,
    }


def string_fields(*names):
    return object_schema(**{name: {"type": "string"} for name in names})


def option_schema(*fields):
    return object_schema(
        options={
            "type": "array",
            "minItems": 3,
            "maxItems": 3,
            "items": string_fields(*fields),
        }
    )


def write_options(spec, tenant, previous=()):
    plan = spec["plan"]
    cfg = model.route("text")
    local_photo = compact_local_vision(cfg)
    if not cfg.get("model") and not model.engine_name():
        weights = Path(
            os.getenv(
                "TRUPIC_VISION_MODEL_DIR",
                Path(__file__).resolve().parents[1]
                / ".trupic/models/Qwen3-VL-2B-Instruct",
            )
        )
        if (
            cfg.get("provider") == "local-rules"
            or not (weights / "Qwen3VL-2B-Instruct-Q4_K_M.gguf").is_file()
        ):
            raise ValueError("请连接文案模型，再获取经过复核的候选文案。")
        port = int(os.getenv("TRUPIC_LOCAL_VISION_PORT", "7395"))
        cfg = {
            "model": "Qwen3-VL-2B-Instruct",
            "url": f"http://127.0.0.1:{port}/v1/chat/completions",
            "provider": "local",
            "key": "",
        }
        local_photo = True

    asset_dir = DATA / tenant / "assets"
    if not local_photo:
        preflight(spec, asset_dir)
    inputs = {
        "需求": plan["original"],
        "商家资料": plan["profile"],
        "已知事实": plan["facts"],
        "原图观察": plan.get("sourceReview", {}).get("reason", ""),
    }
    if plan.get("moment"):
        detail = plan.get("sourceReview", {}).get("visualDetail", {}).get("label")
        if detail:
            inputs["原图观察"] = detail + "。" + inputs["原图观察"]
        inputs["朋友圈选稿要求"] = plan.get("skillPlan", {}).get("instructions", {}).get("copy", [])
    photos = (
        source_images(asset_dir / spec["asset"] / "original.png", None)
        if local_photo and spec.get("asset")
        else []
    )
    skill = wenan.instructions(plan)
    if local_photo:
        # Small device models copy examples from long references verbatim. Keep the
        # active skill's instructions and sharing test, without its worked examples.
        paragraphs = [
            line
            for line in wenan.CORE.splitlines()
            if line.startswith(
                (
                    "- **目标**",
                    "- **依据**",
                    "- **图文分工**",
                    "- **结尾有任务**",
                    "简单改句",
                )
            )
        ]
        if wenan.social_headline(plan):
            paragraphs += [
                wenan.HEADLINE_BRIEF,
                next(
                    line
                    for line in wenan.FORMATS[wenan.SHARING].splitlines()
                    if line.startswith("选稿时")
                ),
            ]
        skill = "\n".join(paragraphs)
    named_subject = plan["profile"].get("name", "")
    if local_photo and photos and not (plan.get("moment") and inputs["原图观察"]):
        try:
            observation = model.chat_request(
                {**cfg, "responseSchema": string_fields("observation", "subject")},
                cfg["model"],
                [
                    {
                        "role": "system",
                        "content": "请用一句话说明这是什么场所或商品，并指出一处最醒目的外观细节。不要写宣传文案，不推测性能。observation 写可见外观。subject 逐字摘录商家需求里项目或商品的名称，没有名称留空。只返回 JSON。",
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": plan["original"]},
                            *photos,
                        ],
                    },
                ],
                140,
                "vision",
            )
        except (OSError, IndexError, KeyError, ValueError) as exc:
            raise ValueError("暂时无法读取原图，请检查本机模型服务后重试。") from exc
        subject = observation.get("subject")
        if (
            isinstance(subject, str)
            and 1 < len(subject) <= 30
            and subject in plan["original"]
        ):
            named_subject = subject
        inputs["原图观察"] = str(observation.get("observation", ""))[:240]

    def ask(task, payload, tokens, schema):
        if not local_photo:
            return model.ask(skill + "\n" + task, payload, tokens)
        messages = [
            {"role": "system", "content": skill + "\n" + task},
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False) + "\n" + task,
            },
        ]
        return model.routed_chat({**cfg, "responseSchema": schema}, messages, tokens, "text")

    base = copy_inputs(plan)
    for key in ("offer", "terms"):
        if value := spec.get("replacement", {}).get(key):
            base[key] = value
    if previous:
        inputs["上一组已展示标题，请换切口"] = previous
    inputs.update(优惠=base["offer"], 条件=base["terms"])
    task = (
        '本次商家要亲自选稿。只返回 JSON {"options":[{"title":"主标题","body":"正文","cta":"行动句","shareTo":"会发给谁","reply":"对方会怎么接"}]}，'
        "写三组真正不同的完整中文海报文案，各用一个角度。"
        "从原图可见细节和需求取材，保留项目或商品名、商业条件，正文和末句各说一件事。"
        "没有指定联系渠道就沿用商家的邀约说法。指定标题逐字保留，通过正文区分选项。"
    )
    task += ("逐字使用商家给出的名称与价格，不纠正片名、不补全品牌。没有提供的档期、限时、"
             "库存、折扣、购票渠道一律不写。标题、副标题和末句合起来只写一次价格。")
    task += wenan.POSTER_HEADINGS
    if wenan.social_headline(plan):
        task += (
            "三组主标题都是微信里能直接发给人的一句话。第一句从我和你的分工入手；"
            "第二句写眼前这个物件能怎么用，带一点朋友间的玩笑；第三句说一个观察到的小细节，让对方想一起去看看。"
            "在每个标题中放一个具体的动作或物件。正文只写商品或项目名加一个真实细节，最多20字。"
            "把时间和预约留给末句。不要用抽象形容词和广告口号。reply 要回应标题，不得重复标题。"
        )
    try:
        locked = LOCKED.search(plan["original"])
        seen = set(previous)
        known = "。".join(
            (
                plan["original"],
                plan["facts"],
                json.dumps(plan["profile"], ensure_ascii=False),
            )
        )
        review_task = (
            "你是独立审稿人。逐组检查事实、商家要求、项目名称、行动。商家原话是名称和价格的依据，按字面核对，不根据常识纠正商家片名或补充品牌。不同角度可以共享同一事实和商品名。"
            '仅返回 JSON {"approved":[0,1,2],"feedback":"未通过稿件需要修正的具体问题"}，数组只列通过的零起始序号。'
        )
        if wenan.social_headline(plan):
            review_task += "逐条检验标题：顾客会把它发给谁，对方能怎么接话，和眼前的商品或场景有什么关系？空泛或换品也成立的标题退稿。"
        approved = []
        feedback = ""
        for attempt in range(2):
            drafts, sharing = [], []
            length_error = ""
            result, engine = ask(
                task, inputs, 900, option_schema("title", "body", "cta", "shareTo", "reply")
            )
            rows = result.get("options")
            if not isinstance(rows, list):
                raise model.InvalidModelOutput("文案模型未返回候选稿，请重试。")
            for row in rows[:3]:
                if not isinstance(row, dict) or not all(
                    isinstance(row.get(k), str) for k in ("title", "body", "cta")
                ):
                    continue
                title, body, cta = (row[k].strip() for k in ("title", "body", "cta"))
                if named_subject and named_subject not in title + body + cta:
                    body = named_subject + (" · " + body if body else "")
                if locked:
                    title = locked.group(1)
                if wenan.no_cta(plan):
                    cta = ""
                elif (
                    not re.search("不(?:能|要|限|在)?周末|周末不|除周末", plan["original"])
                    and cta
                    and "周末" not in title + body + cta
                    and re.search(
                        r"周末[^，。；]{0,30}(?:约个时间|预约|约看)", plan["original"]
                    )
                ):
                    cta = "周末" + cta
                key = (title, body) if locked else title
                if not locked and any(
                    SequenceMatcher(None, title, prior).ratio() >= 0.83 for prior in seen
                ):
                    continue
                if (
                    not title
                    or len(title) > 40
                    or len(cta) > 60
                    or key in seen
                ):
                    continue
                if error := wenan.poster_length_error(title, body, locked):
                    length_error = error
                    continue
                copy_text = f"{title} {body} {cta}"
                if unsupported_copy(copy_text, known):
                    continue
                if wenan.social_headline(plan) and not all(
                    isinstance(row.get(k), str) and row[k].strip()
                    for k in ("shareTo", "reply")
                ):
                    continue
                sharing.append({k: row[k] for k in ("shareTo", "reply") if k in row})
                seen.add(key)
                drafts.append({"title": title, "body": body, "cta": cta})
            if not drafts:
                inputs["改写要求"] = (length_error or "缺少不同角度的合规候选") + "。请生成三组新的候选。"
                continue
            reviewed = {i: {**d, **sharing[i]} for i, d in enumerate(drafts)}
            review, _ = ask(
                review_task,
                {**inputs, "候选": reviewed},
                400,
                object_schema(
                    feedback={"type": "string"},
                    approved={
                        "type": "array",
                        "items": {"type": "integer", "minimum": 0, "maximum": 2},
                    }
                ),
            )
            passed = review.get("approved")
            if not isinstance(passed, list):
                passed = []
            approved.extend([
                {**base, "engine": engine}
                | draft
                | {
                    **({"sharingReview": sharing[i]} if sharing[i] else {}),
                    "detailLine": draft["body"],
                    "review": "商家候选文案已独立复核。",
                    "writingSkill": wenan.record(plan, "模型创作与复核"),
                }
                for i, draft in enumerate(drafts)
                if any(type(n) is int and n == i for n in passed)
            ])
            if len(approved) >= 2:
                return approved[:3]
            feedback = str(review.get("feedback", ""))[:240]
            inputs["改写要求"] = (feedback or "依据商家原话写明商品、价格，避免补充未经证实的描述。") + " 请改写为三个新标题。"
            inputs["已写过的标题"] = [draft["title"] for draft in drafts]
        reason = feedback or length_error
        raise ValueError("通过复核的不同文案不足两组。" + (reason + "。" if reason else "") + "请检查需求中的商品名和卖点后重试。")
    except model.InvalidModelOutput as exc:
        raise ValueError(f"文案模型回复格式异常：{exc} 请重新生成候选。") from exc
    except OSError as exc:
        raise ValueError(model.copy_failure_message(exc)) from exc


def choices_for_quote(quotes, token, tenant, previous=None):
    try:
        q = quotes.loads(token, max_age=1800)
    except BadSignature:
        raise ValueError("创作方案已过期，请重新分析需求。")
    if q.get("tenant") != tenant:
        abort(403)
    spec = next((s for s in proposal_specs(q) if s["kind"] == "poster"), None)
    if not spec:
        raise ValueError("这份方案没有海报。")
    options = []
    previous = (
        [v[:40] for v in previous[:3] if isinstance(v, str)]
        if isinstance(previous, list)
        else []
    )
    for draft in write_options(spec, tenant, previous):
        choice = quotes.dumps(
            {"quoteId": _quote_id(token), "draft": draft, "asset": spec.get("asset"),
             "sourceReview": spec["plan"].get("sourceReview")}, salt="trupic-copy-choice"
        )
        option = {k: draft[k] for k in ("title", "body", "cta")}
        if "spec" in q:
            from .prompt_agent import apply_poster_layout, full_poster_prompt

            apply_poster_layout(spec["plan"], draft)
            option["fullPosterPrompt"] = full_poster_prompt(spec["plan"], draft)
        options.append({**option, "token": choice})
    return options


def selected_copy(quotes, request):
    token = request.get("copyChoice")
    if not isinstance(token, str) or not token or not request.get("quote"):
        raise ValueError("请先选择文案，再制作图片。")
    try:
        choice = quotes.loads(token, salt="trupic-copy-choice", max_age=1800)
    except BadSignature:
        raise ValueError("文案选项已失效，请重新获取。")
    if choice["quoteId"] != _quote_id(request["quote"]):
        raise ValueError("需求已更新，请重新选择本次文案。")
    draft = dict(choice["draft"])
    if choice.get("asset") and choice.get("sourceReview"):
        draft["_source"] = (choice["asset"], choice["sourceReview"])
    return draft


def apply_choice(spec, draft):
    role = spec["plan"].get("bundleRole")
    prior = spec.get("replacement", {})
    result = {**prior, **draft}
    source = result.pop("_source", None)
    if source and source[0] == spec.get("asset"):
        spec["plan"]["sourceReview"] = source[1]
    if role in (
        "scene",
        "white",
        "livebackground",
        "front",
        "side",
        "back",
        "box",
        "bag",
        "card",
    ):
        result["title"] = ""
    elif role == "price":
        result["title"] = draft["offer"] or draft["title"]
    elif role == "closing":
        result["title"] = draft["cta"] or draft["title"]
    elif role == "guideline":
        result["body"] = prior["body"]
    spec["replacement"] = result
    spec["copySelected"] = True
