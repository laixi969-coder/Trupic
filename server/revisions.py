"""Quoted changes to a single immutable work version."""

import re

from .creative import next_suggestion, RISK, NUMCLAIM
from .design import layout_alternative, next_style
from .formats import RATIOS, output_spec
from .prompt_agent import optimize


def short_options(cp):
    sentences = [
        s.strip() for s in re.split(r"(?<=[。！？；])|\n", cp["body"]) if s.strip()
    ]
    required = [
        s for s in sentences if re.search(r"\d|仅限|有效|限量|除外|不叠加|买.*送", s)
    ]
    offers = [v for v in (cp.get("offer"), cp.get("terms")) if v]

    def version(lines):
        kept = list(dict.fromkeys(lines + required))
        text = "".join(kept)
        return " ".join([text, *(v for v in offers if v not in text)]).strip()

    first = version(sentences[:1])
    second = version(sentences[-1:])
    if first == second:
        second = (
            " ".join(filter(None, [cp["title"], first]))
            if cp["title"] not in first
            else version(required) or cp["title"]
        )
    return sorted(dict.fromkeys([first, second]), key=len)


def edit_request(spec, cp, instruction, field):
    """Apply scoped edits to merchant-supplied facts and text; keep the untouched version intact."""
    if not isinstance(instruction, str) or not 1 <= len(instruction.strip()) <= 400:
        raise ValueError("请写下要改的内容。")
    plan = spec["plan"]
    changed = False
    clauses = [s.strip() for s in re.split(r"[；;\n]", instruction) if s.strip()]
    for clause in clauses:
        price = re.fullmatch(
            r"(?:把|将)?(?:价格|售价)?(?:从)?\s*(\d+(?:\.\d+)?)\s*元?\s*(?:改为|改成|调为|调整为|换成|改到)\s*(\d+(?:\.\d+)?)\s*元[。！]?",
            clause,
        )
        if price:
            old, new = price.groups()
            pattern = re.compile(r"(?<![\d.])" + re.escape(old) + r"(?=\s*元)")
            fields = ("title", "body", "detailLine", "cta", "terms", "offer")
            if not any(pattern.search(cp.get(k) or "") for k in fields):
                raise ValueError("作品中找不到这个原价，请核对后再改。")

            def replace(value):
                if isinstance(value, str):
                    return pattern.sub(new, value)
                if isinstance(value, list):
                    return [replace(x) for x in value]
                if isinstance(value, dict):
                    return {k: replace(v) for k, v in value.items()}
                return value

            for k in fields:
                if k in cp:
                    cp[k] = replace(cp[k])
            for k in ("facts", "profile", "coordination", "original", "promptBrief"):
                if k in plan:
                    plan[k] = replace(plan[k])
            cp.pop("fullPosterPrompt", None)
        elif clause in ("换一张", "换个画面", "换版式"):
            if spec["kind"] == "copy":
                raise ValueError("纯文案无法换图。")
            plan["design"] = layout_alternative(plan, cp, spec["kind"])
            plan["layoutOverride"] = True
        else:
            match = re.fullmatch(
                r"(?:把|将)?(标题|正文|行动句)(?:改为|改成|换成)[：:]?(.+)", clause
            )
            if match:
                target = {"标题": "title", "正文": "body", "行动句": "cta"}[match[1]]
                value = match[2].strip("“”")
            elif field in ("title", "body", "cta"):
                target, value = field, clause
            else:
                raise ValueError(
                    "请写明要改的部分，例如“标题改为周末来组局”或“48元改成38元”。多处修改可用分号分开。"
                )
            if RISK.search(value):
                raise ValueError("请核实并调整效果或绝对化声明。")
            cp[target] = value
            if target == "body":
                cp["detailLine"] = value
            plan["facts"] = (plan.get("facts", "") + "；" + value).strip("；")
        changed = True
    if not changed:
        raise ValueError("请填写修改需求。")
    plan["revisionInstruction"] = instruction


def resolve_instruction(spec, cp, instruction, field):
    """Resolve a free-form copy request once, before the merchant confirms the quote."""
    import copy
    from . import model
    try:
        edit_request(copy.deepcopy(spec), copy.deepcopy(cp), instruction, field)
        return instruction
    except ValueError as exc:
        if not str(exc).startswith("请写明要改的部分") or not model.route("text")["model"]:
            raise
    result, _ = model.ask("你修改已有商家文案。仅返回需要替换的字段，可用字段为 title/body/cta。"
        "保留未要求修改的内容及全部交易事实，禁止新增优惠、价格、疗效或承诺。",
        {"instruction":instruction, "existing":{k:cp.get(k,"") for k in ("title","body","cta","offer","terms")},
         "facts":spec["plan"].get("facts","")})
    names={"title":"标题","body":"正文","cta":"行动句"}
    known=" ".join(str(s) for s in [instruction,spec["plan"].get("facts",""),*cp.values()])
    if not result or set(result)-names.keys():
        raise ValueError("无法明确所需的文案修改，请指出要改的文字。")
    clauses=[]
    for key,text in result.items():
        if not isinstance(text,str) or not text.strip() or any(mark in text for mark in ("；",";","\n")):
            raise ValueError("修改稿需要重新整理，请换个说法。")
        if RISK.search(text) or any(claim not in known for claim in NUMCLAIM.findall(text)):
            raise ValueError("修改稿含有未经确认的经营声明。")
        if text != cp.get(key):
            clauses.append(names[key]+"改为"+text)
    resolved="；".join(clauses)
    if not resolved or len(resolved)>400:
        raise ValueError("没有可确认的简短修改，请写明要改的部分。")
    return resolved


def prepare(spec, cp, action, ratio=None, option=0, instruction=None, field=None, region=None):
    plan = spec["plan"]
    if action in ("layout","image","ratio","redesign"):
        plan.pop("backgroundPatches", None)
    if action == "region":
        from .region_edit import validate
        if spec["kind"] != "poster":
            raise ValueError("请选择海报作品。")
        validate(region, instruction, cp.get("protectedAreas",[]))
    elif action in ("layout", "image"):
        if spec["kind"] == "copy":
            raise ValueError("纯文案作品无需换图。")
        design = layout_alternative(plan, cp, spec["kind"])
        plan["design"] = {
            k: v for k, v in design.items() if k not in ("buttonLabel", "layoutIntent")
        }
        plan["layoutOverride"] = True
    elif action == "ratio":
        if ratio not in RATIOS or ratio == spec["ratio"] or spec["kind"] == "copy":
            raise ValueError("请选择其他画幅。")
        previous = plan["output"]
        spec["ratio"] = ratio
        plan["output"] = {
            **previous,
            **output_spec(spec["kind"], ratio, previous["resolution"], previous["dpi"]),
        }
    elif action == "edit":
        edit_request(spec, cp, instruction, field)
    elif action == "shorten":
        values = short_options(cp)
        if type(option) is not int or not 0 <= option < len(values):
            raise ValueError("请选择有效的精简文案。")
        cp.update(body=values[option], detailLine=values[option])
    elif action in ("revision", "redesign"):
        spec["plan"], cp = next_suggestion(spec, cp)
        if action == "redesign" and (design := spec["plan"].get("design")):
            spec["plan"]["design"] = next_style(design)
    else:
        raise ValueError("请选择有效的修改方式。")
    spec["replacement"] = cp
    spec["copySelected"] = True
    optimize(spec, infer=False, previous=plan.get("promptBrief"))
