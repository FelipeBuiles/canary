"""Provider-free promotional back page, independent of production lettering."""

from pathlib import Path
import io

from PIL import Image, ImageDraw, ImageFont
import qrcode


def bookend_image(first_page: bytes, url: str) -> bytes:
    canvas = Image.new("RGB", (1200, 1800), "#FCFAED")
    logo = Image.open(
        Path(__file__).resolve().parents[1] / "assets" / "scenewright-icon.png"
    ).convert("RGBA")
    logo.thumbnail((180, 180))
    canvas.paste(logo, ((1200 - logo.width) // 2, 350), logo)
    draw = ImageDraw.Draw(canvas)
    font_dir = Path(__file__).resolve().parents[1] / "fonts"
    title_font = ImageFont.truetype(str(font_dir / "Bungee-Regular.ttf"), 62)
    body_font = ImageFont.truetype(str(font_dir / "EBGaramond-SemiBold.ttf"), 42)
    for y, text, font in [
        (630, "SCENEWRIGHT", title_font),
        (800, "Every book starts with a story.", body_font),
        (870, "Bring your story to life.", body_font),
        (1050, "scenewright.ink", body_font),
    ]:
        draw.text(
            (600, y),
            text,
            font=font,
            anchor="mm",
            fill="#B51822" if y == 630 else "#1B1C15",
        )
    qr = qrcode.make(url).convert("RGB")
    qr = qr.resize((300, 300), Image.Resampling.NEAREST)
    canvas.paste(qr, (450, 1170))
    buffer = io.BytesIO()
    with Image.open(io.BytesIO(first_page)) as first_image:
        canvas = canvas.resize(first_image.size, Image.Resampling.LANCZOS)
        dpi = first_image.info.get("dpi", (300, 300))
    canvas.save(buffer, "JPEG", quality=95, dpi=dpi)
    return buffer.getvalue()
