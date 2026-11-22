"""Evaluate the delivered-product pixel comparison against labeled export crops."""

import argparse
import json
import math
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.visual_review import package_check


def rectangle(values, normalized=False):
    if (
        not isinstance(values, list)
        or len(values) != 4
        or not all(type(v) in (int, float) and math.isfinite(v) for v in values)
    ):
        raise ValueError("矩形需要四个有限坐标。")
    if (
        values[2] <= values[0]
        or values[3] <= values[1]
        or (normalized and any(v < 0 or v > 1 for v in values))
    ):
        raise ValueError("矩形范围无效。")
    return values


def measure(manifest):
    records = json.loads(manifest.read_text())
    if not isinstance(records, list) or not records:
        raise ValueError("请提供已标注的非空样本列表。")
    results = []
    for idx, row in enumerate(records, 1):
        expected = row["expected"]
        if expected not in ("block", "pass") or not row.get("industry"):
            raise ValueError(f"第 {idx} 条样本缺少行业或人工标签。")
        region = (
            rectangle(row["region"], True) if row.get("region") is not None else None
        )
        mask = None
        if row.get("mask"):
            with Image.open(manifest.parent / row["mask"]) as im:
                mask = im.getchannel("A") if "A" in im.getbands() else im.convert("L")
        with (
            Image.open(manifest.parent / row["photo"]) as photo,
            Image.open(manifest.parent / row["export"]) as export,
        ):
            box = rectangle(row["box"])
            image, ref = export.convert("RGB"), photo.convert("RGB")
            reason = package_check(image, box, ref, mask, None, True)
            if region and not reason:
                reason = package_check(image, box, ref, mask, region, True)
        results.append(
            {
                "sample": row["export"],
                "industry": row["industry"],
                "expected": expected,
                "observed": "block" if reason else "pass",
                "reason": reason,
            }
        )

    def stats(rows):
        valid = [r for r in rows if r["expected"] == "pass"]
        invalid = [r for r in rows if r["expected"] == "block"]
        fp = sum(r["observed"] == "block" for r in valid)
        fn = sum(r["observed"] == "pass" for r in invalid)
        return {
            "samples": len(rows),
            "valid": len(valid),
            "invalid": len(invalid),
            "falsePositives": fp,
            "falseNegatives": fn,
            "falsePositiveRate": fp / len(valid) if valid else None,
            "falseNegativeRate": fn / len(invalid) if invalid else None,
        }

    return {
        "overall": stats(results),
        "industries": {
            k: stats([r for r in results if r["industry"] == k])
            for k in sorted({r["industry"] for r in results})
        },
        "samples": results,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="JSON 文件，图片路径相对于该文件")
    args = parser.parse_args()
    print(json.dumps(measure(args.manifest), ensure_ascii=False, indent=2))
