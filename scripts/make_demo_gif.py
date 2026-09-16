"""Render a split-panel product demo GIF for the loci README.

Left panel: terminal with colored, chunked output (not char-by-char spelling).
Right panel: contextual visual per scene (file cards, search results, IDE graph).
Scene transitions with quick fade. Deterministic — regenerate by editing script."""
from PIL import Image, ImageDraw, ImageFont

W, H = 960, 540
FPS = 12
BG = (7, 11, 7)
FG = (230, 237, 230)
GREEN = (0, 255, 65)
DIM_GREEN = (110, 168, 110)
CYAN = (78, 200, 255)
YELLOW = (255, 209, 102)
ORANGE = (255, 165, 80)
PURPLE = (187, 134, 252)
BAR = (22, 27, 35)
BAR_FG = (140, 160, 170)
CARD_BG = (18, 24, 18)
CARD_BORDER = (40, 60, 40)

def F(size, mono=True):
    for name in ([f"CascadiaCode-{s}.ttf" for s in ("Regular", "PL", "")] +
                 ["CascadiaMono.ttf", "Consolas.ttf", "Couri.ttf",
                  "CascadiaCode-Regular.ttf", "Lucida Console.ttf"] if mono else
                 ["Segoe UI.ttf", "Segoe UI Regular.ttf", "arial.ttf"]):
        try:
            from PIL import ImageFont
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    from PIL import ImageFont
    return ImageFont.load_default()

f_mono = F(15, True)
f_mono_s = F(13, True)
f_ui = F(14, False)
f_ui_s = F(12, False)
f_title = F(20, False)
f_big = F(28, False)


def rounded(d, xy, r=8, fill=None, outline=None, width=1):
    d.rounded_rectangle(xy, radius=r, fill=fill, outline=outline, width=width)


def scene_title_card(frame, t):
    """0-2s: Title card with memory palace quote."""
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    a = min(t / 1.5, 1.0)  # fade in over 1.5s
    c_title = tuple(int(c * a) for c in FG)
    c_dim = tuple(int(c * a * 0.5) for c in DIM_GREEN)
    c_green = tuple(int(c * a) for c in GREEN)
    d.text((W // 2, H // 2 - 50), "loci", font=f_big, fill=c_green, anchor="mm")
    d.text((W // 2, H // 2 + 10),
           "Two thousand years ago, orators stored speeches", font=f_ui, fill=c_dim, anchor="mm")
    d.text((W // 2, H // 2 + 35),
           "in the rooms of a palace and walked through them.", font=f_ui, fill=c_dim, anchor="mm")
    d.text((W // 2, H // 2 + 70),
           "loci does the same for your files.", font=f_ui, fill=c_title, anchor="mm")
    return img


def draw_chrome(img):
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 36], fill=BAR)
    for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        d.ellipse([14 + i * 22, 12, 26 + i * 22, 24], fill=c)
    d.text((W // 2 - 80, 9), "loci — your second brain", font=f_ui_s, fill=BAR_FG)
    # divider
    d.line([0, 36, W, 36], fill=(30, 40, 30), width=1)


def draw_terminal_panel(img, lines, cursor_at=None):
    """lines: [(text, color, indent_level)]"""
    d = ImageDraw.Draw(img)
    d.rectangle([16, 48, 560, H - 16], fill=(10, 14, 10), outline=(30, 45, 30))
    y = 62
    for text, color, indent in lines:
        x = 30 + indent * 18
        d.text((x, y), text, font=f_mono_s, fill=color)
        y += 21
    if cursor_at is not None:
        x = 30 + cursor_at * 18
        d.rectangle([x, y, x + 8, y + 15], fill=GREEN)
    return img


def draw_right_panel_ingest(img, progress):
    """Right side: file cards flying into a central index."""
    d = ImageDraw.Draw(img)
    d.rectangle([576, 48, W - 16, H - 16], fill=CARD_BG, outline=CARD_BORDER)
    d.text((768, 62), "YOUR FILES", font=f_ui_s, fill=DIM_GREEN, anchor="mm")
    files = ["Obsidian notes", "project-docs.pdf", "chat-export.json",
             "README.md", "meeting-notes.md", "architecture.md"]
    for i, name in enumerate(files):
        appeared = progress > i / len(files)
        alpha = min(1.0, max(0, (progress - i / len(files)) * len(files) * 2))
        x = 610 + (i % 2) * 165
        y = 88 + (i // 2) * 52
        c_border = tuple(int(c * alpha) for c in (60, 120, 60)) if alpha < 1 else (60, 120, 60)
        c_text = tuple(int(c * alpha) for c in (200, 220, 200))
        d.rounded_rectangle([x, y, x + 155, y + 38], radius=6,
                            fill=tuple(int(c * alpha) for c in (14, 20, 14)),
                            outline=c_border)
        d.text((x + 10, y + 10), name[:20], font=f_ui_s, fill=c_text)
    # central index icon
    idx_a = min(max((progress - 0.6) * 3, 0), 1.0)
    if idx_a > 0:
        cx, cy = 768, 350
        c_g = tuple(int(c * idx_a) for c in GREEN)
        d.rounded_rectangle([cx - 80, cy - 25, cx + 80, cy + 25], radius=10,
                            outline=c_g, width=2)
        d.text((cx, cy), "📊 hybrid index", font=f_ui_s, fill=c_g, anchor="mm")
        # arrows from files to index
        for i in range(len(files)):
            if progress > (i + 1) / len(files) * 0.6:
                fx = 610 + (i % 2) * 165 + 77
                fy = 88 + (i // 2) * 52 + 19
                d.line([fx, fy, cx, cy], fill=(60, 120, 60), width=1)
    d.text((768, 400), f"{int(progress * 100)}% indexed", font=f_ui_s,
           fill=DIM_GREEN, anchor="mm")


def draw_right_panel_verify(img, progress):
    """Right side: claim check with ✓ appearing one by one."""
    d = ImageDraw.Draw(img)
    d.rectangle([576, 48, W - 16, H - 16], fill=CARD_BG, outline=CARD_BORDER)
    d.text((768, 62), "CLAIM CHECK", font=f_ui_s, fill=DIM_GREEN, anchor="mm")
    claims = [
        ("T8 caches residuals", "excerpt 2", True),
        ("Trajectory forks", "excerpt 2", True),
        ("Same seed → same video", "", False),
    ]
    y = 100
    for i, (claim, src, supported) in enumerate(claims):
        shown = progress > i / len(claims)
        if not shown:
            continue
        mark = "✓" if supported else "✗"
        mc = GREEN if supported else (255, 100, 100)
        d.text((610, y), mark, font=f_mono_s, fill=mc)
        d.text((635, y), claim[:28], font=f_ui_s, fill=FG)
        if src:
            d.text((635, y + 16), f"  [{src}]", font=f_ui_s, fill=DIM_GREEN)
        y += 40
    d.text((768, y + 20), "verifiable ✓", font=f_ui_s, fill=GREEN, anchor="mm")


def draw_right_panel_ide(img, progress):
    """Right side: IDE icons showing cross-IDE shared memory."""
    d = ImageDraw.Draw(img)
    d.rectangle([576, 48, W - 16, H - 16], fill=CARD_BG, outline=CARD_BORDER)
    d.text((768, 62), "ONE STORE, ALL IDEs", font=f_ui_s, fill=DIM_GREEN, anchor="mm")
    ides = [("Claude Code", GREEN), ("Trae", CYAN), ("Qoder", PURPLE), ("Cursor", ORANGE)]
    cx, cy = 768, 200
    for i, (name, color) in enumerate(ides):
        angle = i * 90 + 45
        import math
        ix = cx + int(90 * math.cos(math.radians(angle)))
        iy = cy + int(60 * math.sin(math.radians(angle)))
        a = min(max((progress - i * 0.2) * 3, 0), 1.0)
        if a <= 0:
            continue
        c_border = tuple(int(c * a) for c in color)
        c_text = tuple(int(c * a) for c in FG)
        d.rounded_rectangle([ix - 55, iy - 14, ix + 55, iy + 14], radius=6,
                            outline=c_border, width=1)
        d.text((ix, iy), name, font=f_ui_s, fill=c_text, anchor="mm")
        # line to center
        if a > 0.5:
            d.line([ix, iy, cx, cy], fill=(40, 80, 40), width=1)
    d.ellipse([cx - 20, cy - 20, cx + 20, cy + 20], fill=(10, 20, 10),
              outline=GREEN, width=2)
    d.text((cx, cy), "🧠", font=f_ui, fill=GREEN, anchor="mm")


def scene_ingest(frame, t):
    img = Image.new("RGB", (W, H), BG)
    draw_chrome(img)
    term_lines = [
        ("$ loci ingest", GREEN, 0),
        ("  + hardware-limits.md: 8 chunks", DIM_GREEN, 1),
        ("  + sage-crash.md: 8 chunks (reused 5)", DIM_GREEN, 1),
        ("  + workflows.md: 9 chunks", DIM_GREEN, 1),
        ("Done: 25 added — 68 chunks in store", FG, 0),
    ]
    progress = min(t / 2.5, 1.0)
    visible = int(progress * len(term_lines))
    lines = term_lines[:visible]
    cursor = visible < len(term_lines)
    img = draw_terminal_panel(img, [(l, c, i) for l, c, i in lines], cursor_at=0 if cursor else None)
    draw_right_panel_ingest(img, progress)
    return img


def scene_ask(frame, t):
    img = Image.new("RGB", (W, H), BG)
    draw_chrome(img)
    term_lines = [
        ("$ loci ask \"why does T8 break reruns?\" --verify", GREEN, 0),
        ("Answer:", CYAN, 0),
        ("T8 reuses cached residuals, which forks the", FG, 0),
        ("sampling trajectory — same seed, different video.", FG, 0),
        ("  [source: 08-t8.md > Practical Advice]", DIM_GREEN, 1),
    ]
    progress = min(t / 2.0, 1.0)
    visible = int(progress * len(term_lines))
    lines = term_lines[:visible]
    img = draw_terminal_panel(img, [(l, c, i) for l, c, i in lines])
    draw_right_panel_verify(img, progress)
    return img


def scene_remember(frame, t):
    img = Image.new("RGB", (W, H), BG)
    draw_chrome(img)
    term_lines = [
        ("$ loci remember \"finals: never use T8\"", GREEN, 0),
        ("remembered: memories/20260916-*.md", FG, 0),
        ("(searchable now — shared across IDEs)", DIM_GREEN, 0),
    ]
    progress = min(t / 1.5, 1.0)
    visible = int(progress * len(term_lines))
    lines = term_lines[:visible]
    img = draw_terminal_panel(img, [(l, c, i) for l, c, i in lines])
    draw_right_panel_ide(img, progress)
    return img


scenes = [
    (scene_title_card, 2.0),
    (scene_ingest, 3.0),
    (scene_ask, 2.5),
    (scene_remember, 2.5),
]
total_duration = sum(d for _, d in scenes)
total_frames = int(total_duration * FPS)

frames = []
for scene_fn, duration in scenes:
    n = int(duration * FPS)
    for f in range(n):
        t = f / FPS
        frames.append(scene_fn(f, t))

# hold last frame
for _ in range(FPS):
    frames.append(frames[-1])

out_path = "docs/assets/demo.gif"
frames[0].save(out_path, save_all=True, append_images=frames[1:],
               duration=int(1000 / FPS), loop=0, optimize=True)
import os
print(f"frames: {len(frames)}, size: {os.path.getsize(out_path) // 1024}KB, "
      f"duration: {len(frames) / FPS:.1f}s")
