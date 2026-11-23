"""Exercise the real visual endpoint and both repair paths with a supplied product photo."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def damage_first_export(render, output):
    def render_sample(folder, plan, copy, kind, *args, **kwargs):
        layout = render(folder, plan, copy, kind, *args, **kwargs)
        if kwargs.get("repair"):
            return layout
        if kind == "poster":
            path = folder / "poster.png"
            with Image.open(path) as src:
                image = src.convert("RGB")
                dpi = src.info["dpi"]
            ImageDraw.Draw(image).rectangle(
                layout["frames"][0]["product"], fill="black"
            )
            image.save(path, dpi=dpi)
        else:
            path = folder / "video.mp4"
            changed = folder / "black-shot.mp4"
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-i",
                    str(path),
                    "-vf",
                    "drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill:enable='between(n,72,143)'",
                    "-c:v",
                    "libx264",
                    "-crf",
                    "17",
                    "-c:a",
                    "copy",
                    str(changed),
                ],
                check=True,
            )
            changed.replace(path)
        shutil.copyfile(path, output / (kind + "-first" + path.suffix))
        return layout

    return render_sample


def run(args):
    from server import app as studio
    from server.store import db

    client = studio.app.test_client()
    client.get("/api/state")

    def checked(response):
        if response.status_code != 200:
            raise RuntimeError(response.get_json().get("error", response.status_code))
        return response.get_json()

    def post(route, **payload):
        return checked(client.post("/api/" + route, json=payload))

    if args.profile:
        post("profile", **json.loads(args.profile.read_text()))
    with args.photo.open("rb") as picture:
        asset = checked(
            client.post("/api/assets", data={"image": (picture, args.photo.name)})
        )
    for kind in ("poster", "video"):
        quote = post(
            "preview",
            brief=args.brief,
            kind=kind,
            asset=asset["id"],
            assetMode=args.asset_mode,
            assetConfirmed=True,
            identityRegion=args.region,
        )
        choice = post("copy-options", quote=quote["quote"])["options"][0]["token"] if quote["requiresCopyChoice"] else ""
        job = post(
            "jobs",
            copyChoice=choice,
            quote=quote["quote"],
            confirmed=True,
            confirmedCost=quote["cost"],
            requestKey=uuid.uuid4().hex,
        )
        deadline = time.monotonic() + 420
        while time.monotonic() < deadline:
            status = checked(client.get("/api/jobs/" + job["id"]))
            if status["state"] in ("complete", "failed"):
                break
            time.sleep(0.5)
        else:
            raise RuntimeError(f"{kind} job timed out")
        with db() as connection:
            row = connection.execute(
                "SELECT visual_review FROM job WHERE id=?", (job["id"],)
            ).fetchone()
        report = json.loads(row[0] or "{}")
        evidence = {
            "job": status,
            "source": quote["plan"].get("sourceReview"),
            "review": report,
        }
        (args.output / (kind + "-audit.json")).write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2)
        )
        if status["state"] != "complete" or report.get("status") != "repaired":
            raise RuntimeError(
                f"{kind} failed: {status.get('error') or report.get('status')}"
            )
        attempts = report["attempts"]
        if (
            not evidence["source"]
            or len(attempts) != 2
            or (attempts[0].get("content") or {}).get("status") != "repair"
            or attempts[1]["content"]["status"] != "pass"
            or attempts[1]["issues"]
        ):
            raise RuntimeError(
                f"{kind} needs a model repair verdict and a passing recheck"
            )
        version = checked(client.get("/api/works/" + job["work"]))["versions"][0]
        download = client.get(version["download"])
        if download.status_code != 200:
            raise RuntimeError(f"{kind} download failed")
        if version.get("editSource"):
            edit = client.get(version["editSource"])
            if edit.status_code != 200:
                raise RuntimeError("Video edit package download failed")
            (args.output / "edit.zip").write_bytes(edit.data)
        if version.get("designSource"):
            source = client.get(version["designSource"])
            if source.status_code != 200:
                raise RuntimeError("Design source download failed")
            (args.output / "poster.svg").write_bytes(source.data)
        suffix = ".png" if kind == "poster" else ".mp4"
        (args.output / (kind + suffix)).write_bytes(download.data)
        print(
            f"{kind}: {attempts[0]['content']['status']} → {attempts[1]['content']['status']}",
            flush=True,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--photo", type=Path, required=True)
    parser.add_argument("--brief", required=True)
    parser.add_argument(
        "--asset-mode", choices=("original", "processed"), default="original"
    )
    parser.add_argument("--region", type=float, nargs=4, metavar=("L", "T", "R", "B"))
    parser.add_argument("--profile", type=Path, help="Optional merchant profile JSON")
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New directory for samples and audit records",
    )
    args = parser.parse_args()
    if not os.environ.get("TRUPIC_VISION_MODEL") or not (
        os.environ.get("TRUPIC_MODEL_URL") or os.environ.get("TRUPIC_VISION_URL")
    ):
        parser.error(
            "Configure TRUPIC_VISION_MODEL and its inference endpoint before running"
        )
    args.output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix="trupic-visual-") as directory:
        os.environ["TRUPIC_DATA"] = directory
        from server import app as studio

        with patch.object(
            studio, "render", damage_first_export(studio.render, args.output)
        ):
            run(args)


if __name__ == "__main__":
    main()
