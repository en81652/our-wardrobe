"""Image normalization and portable, dynamically sized outfit cards."""
import base64
import binascii
import io
import re
from datetime import datetime
from zoneinfo import ZoneInfo
import warnings
from pathlib import Path

from fastapi import HTTPException
from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

MAX_IMAGE_BYTES = 5 * 1024 * 1024


def decode_photo(encoded: str) -> bytes:
    try:
        data = base64.b64decode(encoded, validate=True)
        if len(data) > MAX_IMAGE_BYTES:
            raise HTTPException(413, "图片不能超过 5 MB")
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as source:
                if source.width * source.height > 20_000_000:
                    raise HTTPException(413, "图片不能超过 2000 万像素")
                photo = ImageOps.exif_transpose(source).convert("RGB")
                photo.thumbnail((1600, 1600))
                result = io.BytesIO()
                photo.save(result, "JPEG", quality=88)
                return result.getvalue()
    except HTTPException:
        raise
    except (ValueError, binascii.Error, OSError, UnidentifiedImageError,
            Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise HTTPException(422, "图片无效，请使用 JPG、PNG、WebP 或 GIF") from exc


def font_for(size: int, configured: str):
    candidates = [configured, "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc", "NotoSansCJK-Regular.ttc", "NotoSansSC-Regular.ttf",
                  "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                  "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
                  "DejaVuSans.ttf", "Arial.ttf"]
    for candidate in filter(None, candidates):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def wrap_text(pen, text, font, width):
    lines, current = [], ""
    for character in text:
        if character == "\n" or (current and pen.textlength(current + character, font=font) > width):
            lines.append(current)
            current = "" if character == "\n" else character
        else:
            current += character
    return lines + [current]


def text_lines(draw, text, font, width, limit):
    lines, line = [], ""
    for char in text.replace("\r", "").replace("\n", " "):
        if line and draw.textlength(line + char, font=font) > width:
            lines.append(line)
            line = ""
        line += char
    if line:
        lines.append(line)
    if len(lines) > limit:
        lines = lines[:limit]
        while lines[-1] and draw.textlength(lines[-1] + "…", font=font) > width:
            lines[-1] = lines[-1][:-1]
        lines[-1] += "…"
    return lines


def render_card(record: dict, media: Path, font_path: str) -> bytes:
    items, mode, line, timestamp = record["items"], record["mode"], record["line"], record["created_at"]
    target_name, author_name = record["target_name"], record["chosen_by_name"]
    card_font = lambda size: font_for(size, font_path)
    """Up to eight cells; taller three-column cards keep long instructions legible."""
    cream, wine, muted = "#fff9ef", "#672b3c", "#7b635d"
    extra_height = 270 if len(items) > 6 else 0
    card = Image.new("RGB", (1080, 1350 + extra_height), cream)
    draw = ImageDraw.Draw(card)
    draw.rounded_rectangle((26, 26, 1053, 1323 + extra_height), radius=24, outline=wine, width=2)
    heading = author_name + "挑了" if mode == "pick" else "WARDROBE"
    draw.text((66, 59), heading + " · " + target_name + "的衣柜", font=card_font(29), fill=wine)
    date = datetime.fromisoformat(timestamp).astimezone(ZoneInfo("Asia/Shanghai"))
    draw.text((66, 110), date.strftime("%Y.%m.%d  %H:%M") + "  北京时间", font=card_font(22), fill=muted)
    draw.line((66, 158, 1014, 158), fill="#d5beb3", width=1)
    count = len(items)
    columns = 1 if count == 1 else (3 if count > 6 else 2)
    rows = (count + columns - 1) // columns
    gap, start, bottom = 28, 194, 1120 + extra_height
    cell_w = (948 - gap * (columns - 1)) // columns
    cell_h = (bottom - start - gap * (rows - 1)) // rows
    for index, item in enumerate(items):
        x, y = 66 + (index % columns) * (cell_w + gap), start + (index // columns) * (cell_h + gap)
        draw.text((x, y), target_name + item["action"] + " · " + item["category_name"], font=card_font(22), fill=muted)
        photo_y, photo_h = y + 38, cell_h - (144 if rows == 3 else 174)
        tile = Image.new("RGB", (cell_w, photo_h), "#eee1d4")
        if item.get("image_file") and not item.get("text_only"):
            with Image.open(media / item["image_file"]) as source:
                source.draft("RGB", (1000, 1000))
                source.thumbnail((1000, 1000))
                tile = ImageOps.fit(ImageOps.exif_transpose(source).convert("RGB"), (cell_w, photo_h))
        else:
            placeholder = ImageDraw.Draw(tile)
            is_order = item.get("text_only", False)
            words = item["description"] if is_order else item["name"]
            size = 46 if columns == 1 else 34
            # All 200 characters of an instruction remain readable, even in an eight-cell card.
            while True:
                name_font = card_font(size)
                names = text_lines(placeholder, words, name_font, cell_w - 32, 200)
                if len(names) * (size + 4) <= photo_h - 12 or size <= 14:
                    break
                size -= 1
            for offset, name in enumerate(names):
                placeholder.text((cell_w / 2, photo_h / 2 + (offset - (len(names)-1)/2)*(size + 4)),
                                 name, font=name_font, anchor="mm", fill=wine)
        mask = Image.new("L", tile.size)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, cell_w-1, photo_h-1), radius=18, fill=255)
        card.paste(tile, (x, photo_y), mask)
        title_y = photo_y + photo_h + 16
        for offset, name in enumerate(text_lines(draw, item["name"], card_font(28), cell_w, 2)):
            draw.text((x, title_y + offset * 35), name, font=card_font(28), fill=wine)
        sentence = re.split(r"[。！？!?\n]", item["description"], maxsplit=1)[0]
        for note in text_lines(draw, sentence, card_font(21), cell_w, 1):
            draw.text((x, title_y + (65 if rows == 3 else 76)), note, font=card_font(21), fill=muted)
    draw.line((66, 1150 + extra_height, 1014, 1150 + extra_height), fill="#d5beb3", width=1)
    if line:
        # A small slant lends the installed CJK face a handwritten inscription feel.
        inscription = Image.new("RGBA", (948, 90))
        pen = ImageDraw.Draw(inscription)
        for offset, words in enumerate(text_lines(pen, line, card_font(32), 920, 2)):
            pen.text((8, offset * 42), words, font=card_font(32), fill=wine)
        inscription = inscription.transform(inscription.size, Image.Transform.AFFINE,
                                             (1, -0.10, 8, 0, 1, 0), Image.Resampling.BICUBIC)
        card.paste(inscription, (66, 1172 + extra_height), inscription)
    else:
        draw.text((66, 1182 + extra_height), author_name + "挑的" if mode == "pick" else "衣柜开了", font=card_font(32), fill=wine)
    draw.text((1010, 1263 + extra_height), "— " + author_name, font=card_font(26), anchor="ra", fill=wine)
    if record.get("wardrobe_url"):
        for offset, words in enumerate(text_lines(draw, "打开衣柜：" + record["wardrobe_url"], card_font(18), 700, 2)):
            draw.text((66, 1250 + extra_height + offset * 24), words, font=card_font(18), fill=muted)
    output = io.BytesIO()
    card.save(output, "PNG")
    return output.getvalue()


