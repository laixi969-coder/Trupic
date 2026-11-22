"""Export the actual photographic layers and editable text runs of a campaign poster."""

import base64
import io
import xml.etree.ElementTree as ET


def save_source(path, size, images, runs):
    svg = ET.Element(
        "svg",
        {
            "xmlns": "http://www.w3.org/2000/svg",
            "xmlns:xlink": "http://www.w3.org/1999/xlink",
            "width": str(size[0]),
            "height": str(size[1]),
            "viewBox": f"0 0 {size[0]} {size[1]}",
        },
    )
    for name, image, xy in images:
        group = ET.SubElement(svg, "g", id=name)
        if "editable_runs" in image.info:
            write_text(group, image.info["editable_runs"], name)
            continue
        buf = io.BytesIO()
        image.save(buf, "PNG")
        ET.SubElement(
            group,
            "image",
            {
                "x": str(xy[0]),
                "y": str(xy[1]),
                "width": str(image.width),
                "height": str(image.height),
                "xlink:href": "data:image/png;base64,"
                + base64.b64encode(buf.getvalue()).decode(),
            },
        )
    text = ET.SubElement(svg, "g", id="typography")
    write_text(text, runs, "text")
    ET.ElementTree(svg).write(path, encoding="utf-8", xml_declaration=True)


def write_text(text, runs, prefix):
    for i, line in enumerate(runs):
        group = ET.SubElement(text, "g", id=f"{prefix}-{i + 1}")
        for (x, y), value, f, fill in line:
            family, style = f.getname()
            ET.SubElement(
                group,
                "text",
                {
                    "x": str(x),
                    "y": str(y),
                    "font-family": family,
                    "font-size": str(f.size),
                    "font-weight": "700" if "bold" in style.lower() else "400",
                    "xml:space": "preserve",
                    "fill": fill,
                },
            ).text = value
