"""Render a terminal-session demo GIF for the loci README.

Simulates a real CLI session (typed commands + outputs, dark terminal window)
with PIL — deterministic, no screen recording needed. ~14s loop."""
from PIL import Image, ImageDraw, ImageFont

W, H = 880, 460
FPS = 12
BG = (10, 14, 10)
FG = (0, 255, 65)
DIM = (110, 168, 110)
CYAN = (78, 200, 255)
YELLOW = (255, 209, 102)
BAR = (28, 40, 28)
BAR_FG = (170, 184, 170)

# 每帧脚本: (text, color, is_command) — 命令逐字打, 输出整行出
script = [
    ("$ loci ingest", None, True),
    ("  + hardware-limits.md: 8 chunks", DIM, False),
    ("  + sage-crash.md: 8 chunks (reused 5 embeddings)", DIM, False),
    ("  + workflows.md: 9 chunks", DIM, False),
    ("Done: 25 added / 0 updated — 68 chunks in store", FG, False),
    ("", None, False),
    ("$ loci ask \"why does T8 break same-seed reruns?\" --verify", None, True),
    ("Answer:", CYAN, False),
    ("T8 reuses residuals from cached steps, which forks the", FG, False),
    ("sampling trajectory — same seed, different video.", FG, False),
    ("  [source: 08-t8-blockcache.md > Practical Advice]", DIM, False),
    ("Claim check:", CYAN, False),
    ("  + T8 caches residuals            [excerpt 2]", FG, False),
    ("  + trajectory forks               [excerpt 2]", FG, False),
    ("", None, False),
    ("$ loci remember \"finals: never use T8\"", None, True),
    ("remembered: memories/20260916-*.md (searchable now)", FG, False),
    ("", None, False),
    ("$ loci wiki \"t8 acceleration\"", None, True),
    ("wiki page written: wiki/t8-acceleration.md", FG, False),
    ("distilled 12 excerpts — searchable, linked", FG, False),
]

def find_font(size):
    for name in ("CascadiaMono.ttf", "Consolas.ttf", "Courier New.ttf", "Lucon.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.truetype("arial.ttf", size)

font = find_font(17)
title_font = find_font(13)

def draw_window(lines, cursor_col=None, cursor_line=None):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    # title bar
    d.rectangle([0, 0, W, 30], fill=BAR)
    d.ellipse([12, 11, 24, 23], fill=(255, 95, 86))
    d.ellipse([32, 11, 44, 23], fill=(255, 189, 46))
    d.ellipse([52, 11, 64, 23], fill=(39, 201, 63))
    d.text((W // 2 - 90, 8), "loci — your second brain", font=title_font, fill=BAR_FG)
    y = 44
    for (text, color, is_cmd), (shown, cursor) in lines:
        if not shown and cursor is None:
            y += 24
            continue
        display = shown
        if is_cmd:
            d.text((18, y), "$ ", font=font, fill=YELLOW)
            d.text((38, y), display, font=font, fill=FG)
            if cursor:
                x = 38 + d.textlength(display, font=font)
                d.rectangle([x + 1, y + 1, x + 9, y + 17], fill=FG)
        else:
            c = color or FG
            d.text((38, y), display, font=font, fill=c)
        y += 24
    return img

frames = []
state = []           # (script entry, (shown_text, cursor_bool))
typing_speed = 2     # chars per frame
hold_output = 3      # frames per output line

for entry in script:
    text, color, is_cmd = entry
    if is_cmd:
        for i in range(0, len(text) + typing_speed, typing_speed):
            state.append((entry, (text[:i], True)))
            frames.append(draw_window(state))
        state[-1] = (entry, (text, None))          # cursor rest
        for _ in range(4):
            frames.append(draw_window(state))
    else:
        state.append((entry, (text, None)))
        for _ in range(hold_output):
            frames.append(draw_window(state))

# 末尾停留 + 闪烁光标
state.append((("", None, True), ("", True)))
for i in range(24):
    frames.append(draw_window(state[:-1] + [state[-1]] if i % 8 < 5 else state[:-1] + [(state[-1][0], ("", False))]))

frames[0].save(
    "docs/assets/demo.gif", save_all=True, append_images=frames[1:],
    duration=int(1000 / FPS), loop=0, optimize=True)
print(f"frames: {len(frames)}, ~{len(frames) / FPS:.0f}s")
