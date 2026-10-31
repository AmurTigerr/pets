from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from matplotlib import font_manager


OUT = Path("mermaid_component_diagram.png")
W, H = 2600, 1700

BG = "#0e081a"
BOX = "#2a1a44"
BOX_DARK = "#31163f"
GROUP = "#231532"
EDGE = "#8a5cff"
ACCENT = "#f08ad8"
TEXT = "#f5efff"
MUTED = "#cdbbea"
ARROW = "#cbb7ff"


def f(size, bold=False):
    path = font_manager.findfont("DejaVu Sans", fallback_to_default=True)
    if bold:
        candidate = Path(path).with_name("DejaVuSans-Bold.ttf")
        if candidate.exists():
            path = str(candidate)
    return ImageFont.truetype(path, size)


def box(draw, xy, fill, outline, radius=30, width=5):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def label(draw, box_xy, title, body, title_size=42, body_size=27):
    x1, y1, x2, y2 = box_xy
    cx = (x1 + x2) / 2
    draw.text((cx, y1 + 28), title, fill=TEXT, font=f(title_size, True), anchor="ma")
    draw.multiline_text(
        (cx, y1 + 122),
        body,
        fill=TEXT,
        font=f(body_size),
        anchor="ma",
        align="center",
        spacing=8,
    )


def arrow(draw, start, end, color=ARROW, width=8):
    draw.line([start, end], fill=color, width=width)
    sx, sy = start
    ex, ey = end
    dx, dy = ex - sx, ey - sy
    length = max((dx * dx + dy * dy) ** 0.5, 1)
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    head = 24
    p1 = (ex, ey)
    p2 = (ex - ux * head + px * head * 0.6, ey - uy * head + py * head * 0.6)
    p3 = (ex - ux * head - px * head * 0.6, ey - uy * head - py * head * 0.6)
    draw.polygon([p1, p2, p3], fill=color)


img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)

d.text((W / 2, 70), "Компонентная диаграмма системы Elen Tech", fill=TEXT, font=f(54, True), anchor="ma")
d.text((W / 2, 140), "Показывает основные блоки и связи между ними", fill=MUTED, font=f(28), anchor="ma")

# Top row
user = (70, 260, 360, 500)
frontend = (430, 260, 850, 500)
backend = (960, 260, 1380, 500)
db = (1490, 260, 1910, 500)

box(d, user, BOX_DARK, EDGE)
box(d, frontend, BOX_DARK, "#7d4fe5")
box(d, backend, "#34163d", "#9a67ff", radius=38)
box(d, db, BOX_DARK, "#6c58ff")

label(d, user, "Пользователь", "Вход\nРабота с сайтом", 34, 24)
label(d, frontend, "Frontend", "Главная / auth / cabinet\nquestionnaire / favorites\nstyles.css / script.js", 36, 24)
label(d, backend, "Flask Backend", "Регистрация / вход\nЛичный кабинет\nАнкета и избранное\nСброс пароля и коды", 35, 23)
label(d, db, "SQLite", "users\nquestionnaires\nfavorites", 38, 26)

# External services group
services_group = (340, 640, 2260, 1110)
box(d, services_group, GROUP, EDGE, radius=40, width=6)
d.text((1300, 690), "External services", fill=TEXT, font=f(34, True), anchor="ma")
d.text((1300, 735), "Службы, которые подключаются к backend", fill=MUTED, font=f(24), anchor="ma")

openrouter = (480, 830, 850, 1025)
image_model = (960, 830, 1330, 1025)
smtp = (1440, 830, 1810, 1025)

box(d, openrouter, BOX, ACCENT, radius=28)
box(d, image_model, BOX, ACCENT, radius=28)
box(d, smtp, BOX, ACCENT, radius=28)

label(d, openrouter, "OpenRouter", "Анализ анкеты", 32, 18)
label(d, image_model, "Hugging Face", "10 образов\nпо анкете", 30, 18)
label(d, smtp, "SMTP", "Письмо с кодом\nна почту", 34, 18)

# Arrows
arrow(d, (360, 380), (430, 380))
arrow(d, (850, 380), (960, 380))
arrow(d, (1380, 380), (1490, 380))
arrow(d, (1170, 500), (1170, 640))
arrow(d, (1230, 500), (1230, 820))
arrow(d, (1245, 500), (1245, 820))

# Connections from backend to external services
arrow(d, (1150, 640), (665, 830))
arrow(d, (1170, 640), (1125, 830))
arrow(d, (1190, 640), (1625, 830))

img.save(OUT)
print(f"saved {OUT.resolve()}")
