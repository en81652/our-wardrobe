"""Draw our own geometric wardrobe icon. No external artwork or fonts."""
from pathlib import Path

from PIL import Image, ImageDraw

destination = Path(__file__).resolve().parents[1] / "static"
scale = 4
image = Image.new("RGB", (512 * scale, 512 * scale), "#F7FAFC")
pen = ImageDraw.Draw(image)
box = lambda values: tuple(value * scale for value in values)
pen.rounded_rectangle(box((130, 106, 382, 406)), radius=30 * scale, fill="#672b3c")
pen.rounded_rectangle(box((142, 118, 370, 394)), radius=18 * scale, fill="#fff9ef")
pen.line(box((256, 118, 256, 394)), fill="#672b3c", width=8 * scale)
for x in (230, 282):
    pen.ellipse(box((x - 10, 252, x + 10, 272)), fill="#672b3c")
for size in (180, 192, 512):
    image.resize((size, size), Image.Resampling.LANCZOS).save(destination / f"icon-{size}.png")
