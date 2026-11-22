"""All advertised raster sizes use an exact aspect ratio and even dimensions."""

RATIOS = {
    "portrait": (3, 4),
    "square": (1, 1),
    "story": (9, 16),
    "feed": (4, 5),
    "landscape": (16, 9),
}
SHORT_EDGES = (720, 1080, 2160)
PRINT_DPI = (72, 150, 300)


def output_spec(kind, ratio, resolution=None, dpi=None):
    if ratio not in RATIOS:
        raise ValueError("请选择支持的画幅。")
    edge = resolution if resolution is not None else (720 if kind == "video" else 1080)
    if isinstance(edge, bool) or str(edge) not in {str(n) for n in SHORT_EDGES}:
        raise ValueError("请选择支持的导出分辨率。")
    dpi = 300 if dpi is None else dpi
    if str(dpi) not in {str(n) for n in PRINT_DPI}:
        raise ValueError("请选择支持的印刷精度。")
    a, b = RATIOS[ratio]
    unit = int(edge) // min(a, b)
    return {
        "ratio": ratio,
        "resolution": int(edge),
        "width": a * unit,
        "height": b * unit,
        "dpi": int(dpi),
    }
