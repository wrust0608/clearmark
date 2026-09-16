"""Build the ClearMark multi-resolution Windows icon."""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


def build_icon(output: Path) -> None:
    scale = 4
    canvas = Image.new("RGBA", (256 * scale, 256 * scale), (0, 0, 0, 0))

    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle((75, 91, 949, 965), radius=225, fill=(18, 35, 26, 78))
    shadow = shadow.filter(ImageFilter.GaussianBlur(34))
    canvas.alpha_composite(shadow)

    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((72, 64, 952, 944), radius=225, fill="#14231b")
    draw.ellipse((155, 146, 869, 860), fill="#193e2b")
    draw.ellipse((230, 218, 794, 782), fill="#173424")

    mark = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    mark_draw = ImageDraw.Draw(mark)
    mark_draw.rounded_rectangle((272, 365, 758, 425), radius=30, fill="#5de18e")
    mark_draw.rounded_rectangle((272, 523, 640, 583), radius=30, fill="#5de18e")
    mark = mark.rotate(350, resample=Image.Resampling.BICUBIC, center=(512, 512))
    canvas.alpha_composite(mark)

    draw = ImageDraw.Draw(canvas)
    draw.ellipse((795, 216, 836, 257), fill="#f4f1e8")

    output.parent.mkdir(parents=True, exist_ok=True)
    icon = canvas.resize((256, 256), Image.Resampling.LANCZOS)
    icon.save(output, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    icon.save(output.with_suffix(".png"), format="PNG")


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("assets/ClearMark.ico")
    build_icon(target)
