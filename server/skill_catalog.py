"""Locally executable creative workflows and their delivery contracts."""

SKILLS = {
    "launch": {
        "name": "商品上新",
        "description": "主图、卖点图、场景图，合格抠图另出白底图。",
        "roles": ["hero", "benefit", "scene"],
    },
    "promotion": {
        "name": "促销活动",
        "description": "统一活动主视觉、促销海报、价格图与横幅。填写已确认的优惠及有效期。",
        "roles": ["campaign", "promotion", "price", "banner"],
    },
    "social": {
        "name": "小红书组图",
        "description": "封面、卖点展开页、收尾页，共用品牌与商品信息。",
        "roles": ["cover", "detail", "closing"],
    },
    "live": {
        "name": "直播素材",
        "description": "直播预告、封面、背景和透明文字贴片。填写开播时间。",
        "roles": ["announcement", "livecover", "livebackground", "overlay"],
    },
    "brand": {
        "name": "品牌识别",
        "description": "保存品牌名称、Logo、色板和字体，交付品牌规范卡与应用示例。",
        "roles": ["guideline", "brandcard", "brandbanner"],
    },
    "motion": {
        "name": "动态海报",
        "description": "海报与九秒三镜短片，输出 MP4 和可继续剪辑的素材。",
        "roles": ["hero", "motion"],
    },
    "mockup": {
        "name": "物品样机",
        "description": "把上传的 Logo 应用到平面包装盒、手提袋和品牌卡的概念样机。",
        "roles": ["box", "bag", "card"],
    },
    "angles": {
        "name": "多角度商品图",
        "description": "使用同一商品的正面、侧面和背面实拍，统一排版交付三张。",
        "roles": ["front", "side", "back"],
    },
    "remake": {
        "name": "视频重制",
        "description": "选择已有 Trupic 九秒短片，沿用画幅与版式，替换商品和文案。",
        "roles": ["remake"],
    },
}
ROLE_NAMES = dict(
    hero="主图",
    benefit="卖点图",
    scene="场景图",
    white="白底图",
    campaign="活动主视觉",
    promotion="促销海报",
    price="价格图",
    banner="活动横幅",
    cover="小红书封面",
    detail="卖点展开页",
    closing="收尾页",
    announcement="直播预告",
    livecover="直播封面",
    livebackground="直播背景",
    overlay="透明贴片",
    guideline="品牌规范",
    brandcard="品牌应用卡",
    brandbanner="品牌横幅",
    motion="动态海报短片",
    box="包装盒样机",
    bag="手提袋样机",
    card="品牌卡样机",
    front="正面图",
    side="侧面图",
    back="背面图",
    remake="重制短片",
)
VIDEO_ROLES = {"motion", "remake"}
