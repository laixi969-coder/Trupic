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

    def ask(task, payload, tokens, schema, *, review=False):
        instructions = task if review and not wenan.social_headline(plan) else skill + "\n" + task
        if not local_photo:
            return model.ask(instructions, payload, tokens)
        messages = [
            {"role": "system", "content": instructions},
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
        '本次商家要亲自选稿。只返回 JSON {"options":[{"title":"一级主标题(社交钩子)","body":"二级副标题(卖点/事实)","cta":"三级行动收口","socialPost":"四级朋友圈/小红书配发正文","angle":"4字角度标签","visualIdea":"配套商业广告画面构思","shareTo":"会发给谁","reply":"对方会怎么接"}]}，'
        "写三组真正不同的完整中文海报多层级文案，各用一个角度。"
        "从原图可见细节和需求取材，保留项目或商品名、商业条件，各级文案分工明确、形成从钩子→信任→行动的闭环。"
        "没有指定联系渠道就沿用商家的邀约说法。指定标题逐字保留，通过副标题与配发正文区分选项。"
    )
    task += ("逐字使用商家给出的名称与价格，不纠正片名、不补全品牌。没有提供的档期、限时、"
             "库存、折扣、购票渠道一律不写。标题、副标题和末句合起来只写一次价格。")
    task += wenan.POSTER_HEADINGS
    if plan.get("capability") and not wenan.factual_only(plan["original"]):
        task += wenan.SOCIAL_CURRENCY_CLOSED_LOOP
    creative_title = wenan.wants_creative_headline(plan["original"])
    single_price = re.fullmatch(r"\d+(?:\.\d+)?元", (base["offer"] or "").strip())
    if creative_title:
        task += wenan.POSTER_CREATIVE_BRIEF
        inputs["三组选稿方向"] = [
            "看画面：选一处最值得多看一眼的细节，用一句话点出来。",
            "看顾客：替顾客说出与这个商品有关的一句邀约或心里话，另选切入点。",
            "看卖点：把一条已知事实写成选择它的理由。各组选不同角度，最多一组主打票价或售价，其余在副标题标价。",
        ]
    if wenan.social_headline(plan):
        task += (
            "三组主标题都是微信里能直接发给人的一句话。第一句从我和你的分工入手；"
            "第二句写眼前这个物件能怎么用，带一点朋友间的玩笑；第三句说一个观察到的小细节，让对方想一起去看看。"
            "在每个标题中放一个具体的动作或物件。正文只写商品或项目名加一个真实细节，最多20字。"
            "把时间和预约留给末句。不要用抽象形容词和广告口号。reply 要回应标题，不得重复标题。"
        )
    fields = ("title", "body", "cta", "shareTo", "reply")
    if plan.get("capability"):
        inputs["本次图文构思"] = {
            "商品": plan.get("promptBrief", {}).get("reading", {}).get("product"),
            "客群": plan.get("audience"), "切入角度": plan.get("angle"),
        }
        if local_photo and not wenan.social_headline(plan):
            fields = ("title", "body", "cta")
            task = (
                "请创作三份可直接发布的中文海报文字。第一份主标题写顾客眼前的具体瞬间，"
                "第二份主标题是一位顾客邀请朋友时会说的话，第三份主标题写选择这个商品的具体理由。"
                "从需求提取信息，用自己的句子表达。只在副标题补齐商品名及已知条件。"
                "没有证据的优惠、价格、功效不能写。指定标题原样使用。"
                + wenan.POSTER_HEADINGS
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
            '仅返回 JSON {"approved":[0,1,2],"feedback":"未通过稿件需要修正的具体问题"}，数组只列通过的零起始序号。feedback 至多40字，不写逐稿分析，全部通过时留空。'
        )
        if creative_title:
            review_task += "逐组检查主标题是否提出了新的观察、动作、问题或购买理由。只复述品名和价格、只换词序或加泛用赞词的退稿；价格用数字和汉字写了两遍、给普通售价加上未说明的促销或上市状态，也要退稿。写“回归、重映、返场”等上市状态必须有明确依据。全稿应能读出宣传的商品和重要条件。几句围绕同一个动作换形容词或问句算同一角度，最多保留一条。在 feedback 点出要改哪里。"
        if wenan.social_headline(plan):
            review_task += "逐条检验标题：顾客会把它发给谁，对方能怎么接话，和眼前的商品或场景有什么关系？空泛或换品也成立的标题退稿。"
        approved = []
        feedback = ""
        schema = option_schema(*fields)
        if plan.get("capability") and local_photo and not locked:
            headings = schema["properties"]["options"]["items"]["properties"]
            headings["title"].update(minLength=8, maxLength=18, description="一句给顾客看的主标题")
            headings["body"].update(maxLength=20, description="补充商品或经营事实的副标题")
        for attempt in range(2):
            drafts, sharing = [], []
            draft_error = ""
            result, engine = ask(
                task, inputs, 900, schema
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
                    draft_error = error
                    continue
                if error := wenan.cliche_error(f"{title} {body} {cta}", plan["original"]):
                    draft_error = error
                    continue
                if creative_title and wenan.copied_headline(title, plan["original"]):
                    draft_error = "主标题照搬了需求，请从画面细节或顾客动机另写标题，品名和条件放副标题"
                    continue
                copy_text = f"{title} {body} {cta}"
                if creative_title and single_price and not wenan.no_cta(plan):
                    amount = single_price.group()
                    price_count = len(re.findall(r"(?<![\d.])" + re.escape(amount), re.sub(r"\s+", "", copy_text)))
                    if price_count != 1:
                        draft_error = f"请把已确认的价格{amount}按原样写一次，方便商家核对"
                        continue
                    if amount in title and any(amount in item["title"] for item in [*drafts, *approved]):
                        draft_error = "已有一组在标题强调价格。请换一个顾客视角，在副标题标价"
                        continue
                if unsupported_copy(copy_text, known):
                    continue
                if wenan.social_headline(plan) and not all(
                    isinstance(row.get(k), str) and row[k].strip()
                    for k in ("shareTo", "reply")
                ):
                    continue
                sharing.append({k: row[k] for k in ("shareTo", "reply") if k in row})
                seen.add(key)
                default_angles = ("画面切入", "顾客邀约", "卖点理由")
                angle_tag = (
                    row.get("angle", "").strip()[:12]
                    if isinstance(row.get("angle"), str) and row.get("angle").strip()
                    else default_angles[len(drafts) % len(default_angles)]
                )
                visual_idea = (
                    row.get("visualIdea", "").strip()[:120]
                    if isinstance(row.get("visualIdea"), str)
                    else ""
                )
                social_post = (
                    row.get("socialPost", "").strip()[:260]
                    if isinstance(row.get("socialPost"), str)
                    else ""
                )
                draft_item = {"title": title, "body": body, "cta": cta, "angle": angle_tag}
                if visual_idea:
                    draft_item["visualIdea"] = visual_idea
                if social_post and not unsupported_copy(social_post, known) and not wenan.cliche_error(social_post, plan["original"]):
                    draft_item["socialPost"] = social_post
                if isinstance(row.get("shareTo"), str) and row["shareTo"].strip():
                    draft_item["shareTo"] = row["shareTo"].strip()[:40]
                if isinstance(row.get("reply"), str) and row["reply"].strip():
                    draft_item["reply"] = row["reply"].strip()[:60]
                drafts.append(draft_item)
            if not drafts:
                inputs["改写要求"] = (draft_error or "缺少不同角度的合规候选") + "。请生成三组新的候选。"
                continue
            reviewed = {i: {**d, **sharing[i]} for i, d in enumerate(drafts)}
            review_schema = object_schema(
                feedback={"type": "string", "maxLength": 80},
                approved={"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 2}},
            )
            review_input = {**inputs, "候选": reviewed}
            if approved:
                review_input["已保留，不再评序号"] = [item["title"] for item in approved]
            try:
                review, _ = ask(review_task, review_input, 768, review_schema, review=True)
            except model.InvalidModelOutput:
                review, _ = ask(review_task + " 只输出所需 JSON。", review_input, 1200, review_schema, review=True)
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
            inputs["改写要求"] = (feedback or draft_error or "依据商家原话写明商品、价格，避免补充未经证实的描述。") + " 请改写为三个新标题。"
            inputs["已写过的标题"] = [draft["title"] for draft in drafts]
        if approved:
            return approved[:3]
        reason = feedback or draft_error
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
