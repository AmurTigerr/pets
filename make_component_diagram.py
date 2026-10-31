from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from matplotlib import font_manager


OUT = Path("component_diagram.png")
W, H = 2200, 1300

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


def box(draw, xy, fill, outline, radius=34, width=5):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def label(draw, box_xy, title, body, title_size=44, body_size=28):
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

user = (60, 260, 440, 500)
frontend = (500, 260, 880, 500)
backend = (980, 260, 1360, 500)
db = (1460, 260, 1840, 500)

services_group = (360, 610, 1860, 990)

box(d, user, BOX_DARK, EDGE)
box(d, frontend, BOX_DARK, "#7d4fe5")
box(d, backend, "#34163d", "#9a67ff", radius=38)
box(d, db, BOX_DARK, "#6c58ff")
box(d, services_group, GROUP, ACCENT, radius=38)

label(d, user, "Пользователь", "Браузер", 36, 22)
fx1, fy1, fx2, fy2 = frontend
fcx = (fx1 + fx2) / 2
d.text((fcx, fy1 + 28), "Frontend", fill=TEXT, font=f(38, True), anchor="ma")
d.multiline_text(
    (fcx, fy1 + 112),
    "Шаблоны\nJS/CSS",
    fill=TEXT,
    font=f(18),
    anchor="ma",
    align="center",
    spacing=6,
)
bx1, by1, bx2, by2 = backend
bcx = (bx1 + bx2) / 2
d.text((bcx, by1 + 28), "Flask Backend", fill=TEXT, font=f(36, True), anchor="ma")
d.multiline_text(
    (bcx, by1 + 96),
    "Регистрация\nАнкета\nИзбранное\nСброс пароля\nОбразы",
    fill=TEXT,
    font=f(15),
    anchor="ma",
    align="center",
    spacing=4,
)
label(d, db, "SQLite", "users\nquestionnaires\nfavorites", 36, 22)

d.text((1100, 640), "External services", fill=TEXT, font=f(34, True), anchor="ma")
d.text((1100, 685), "Службы, которые подключаются к backend", fill=MUTED, font=f(24), anchor="ma")

openrouter = (490, 760, 810, 970)
image_model = (940, 760, 1260, 970)
smtp = (1390, 760, 1710, 970)

box(d, openrouter, BOX, ACCENT, radius=28)
box(d, image_model, BOX, ACCENT, radius=28)
box(d, smtp, BOX, ACCENT, radius=28)

label(d, openrouter, "OpenRouter", "Анализ анкеты", 28, 16)
label(d, image_model, "Hugging Face", "10 образов\nпо анкете", 28, 16)
label(d, smtp, "SMTP", "Письмо с кодом\nна почту", 28, 16)

# Main flow
arrow(d, (440, 380), (500, 380))
arrow(d, (880, 380), (980, 380))
arrow(d, (1360, 380), (1460, 380))

# Backend to services group
arrow(d, (1170, 500), (1170, 610))

img.save(OUT)
print(f"saved {OUT.resolve()}")
