"""
Swiss-minimalist design system for s3Uploader.

Centralizes the visual language: a neutral palette with a single accent,
a grid-based spacing scale, one typographic family, and a set of flat,
monochromatic line icons rendered with PIL (no emojis).

Everything here is theme-aware. CustomTkinter accepts a (light, dark) tuple
for most colors, so tokens are exposed as tuples and the icon factory picks
the tone that matches the current appearance mode.
"""

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageChops


# --------------------------------------------------------------------------
# Palette: neutrals + a single accent (International / Swiss style)
# --------------------------------------------------------------------------
# Tuples are (light_mode, dark_mode).

class Color:
    # Surfaces
    BG = ("#FFFFFF", "#101113")          # main canvas
    SURFACE = ("#FFFFFF", "#17181B")     # cards / panels
    SIDEBAR = ("#F4F4F5", "#0B0C0E")     # left rail
    SUBTLE = ("#FAFAFA", "#1C1D21")      # hover / inset

    # Lines & separators
    LINE = ("#E4E4E7", "#2A2B30")
    LINE_STRONG = ("#D4D4D8", "#3A3B42")

    # Text
    TEXT = ("#18181B", "#FAFAFA")        # primary
    TEXT_MUTED = ("#71717A", "#9CA3AF")  # secondary
    TEXT_FAINT = ("#A1A1AA", "#6B7280")  # tertiary / hints

    # Single accent (used sparingly for the active / primary action).
    # Derived from the app icon's violet so the accent reinforces the brand.
    ACCENT = ("#6D28D9", "#8B5CF6")      # Brand violet
    ACCENT_HOVER = ("#5B21B6", "#A78BFA")
    ON_ACCENT = ("#FFFFFF", "#FFFFFF")

    # One functional danger tone, kept muted
    DANGER = ("#B42318", "#F04438")

    # Neutral control (secondary buttons): transparent with a border
    CONTROL_HOVER = ("#EFEFF1", "#232428")


# --------------------------------------------------------------------------
# Content colors: flat, de-saturated hues to tint file-type and folder icons.
# Flat != monochrome - these stay in one calm tonal register so the grid reads
# as colorful-but-clean, never noisy. Each is (light, dark): a touch deeper in
# light mode, a touch brighter in dark mode, for legibility on both surfaces.
# Only type/folder/bucket icons use these; action icons stay neutral so color
# means "what kind of thing this is", not "what this button does".
# --------------------------------------------------------------------------
class IconColor:
    FOLDER = ("#2563EB", "#60A5FA")   # blue
    BUCKET = ("#7C3AED", "#A78BFA")   # violet (brand family)
    IMAGE = ("#0D9488", "#2DD4BF")    # teal
    AUDIO = ("#DB2777", "#F472B6")    # pink
    VIDEO = ("#DC2626", "#F87171")    # red
    ARCHIVE = ("#CA8A04", "#FACC15")  # amber
    DOC = ("#4F46E5", "#818CF8")      # indigo
    GENERIC = ("#64748B", "#94A3B8")  # slate (unknown types)


# Map an icon name to its content color.
ICON_COLOR_BY_NAME = {
    "image": IconColor.IMAGE,
    "audio": IconColor.AUDIO,
    "video": IconColor.VIDEO,
    "archive": IconColor.ARCHIVE,
    "doc": IconColor.DOC,
    "file": IconColor.GENERIC,
}


# --------------------------------------------------------------------------
# Typography: one grotesque family, hierarchy by size/weight only
# --------------------------------------------------------------------------
FONT_FAMILY = "Helvetica Neue"


# Global scale applied to type and icon sizes. Bumped to 1.1 so text and
# icons read ~10% larger without touching the spacing grid.
UI_SCALE = 1.1


def _fs(size):
    return int(round(size * UI_SCALE))


def font(size=13, weight="normal"):
    return (FONT_FAMILY, _fs(size), weight)


class Type:
    DISPLAY = (FONT_FAMILY, _fs(22), "bold")
    TITLE = (FONT_FAMILY, _fs(16), "bold")
    HEADING = (FONT_FAMILY, _fs(13), "bold")
    BODY = (FONT_FAMILY, _fs(13), "normal")
    LABEL = (FONT_FAMILY, _fs(12), "normal")
    CAPTION = (FONT_FAMILY, _fs(11), "normal")
    MONO = ("Menlo", _fs(11), "normal")


# --------------------------------------------------------------------------
# Spacing: a strict 4px grid. Reach for these instead of magic numbers.
# --------------------------------------------------------------------------
class Space:
    XS = 4
    SM = 8
    MD = 12
    LG = 16
    XL = 24
    XXL = 32


RADIUS = 8
RADIUS_SM = 6


# --------------------------------------------------------------------------
# Button recipes: keep the call sites declarative and consistent
# --------------------------------------------------------------------------
def primary_button_kwargs():
    return dict(
        font=Type.HEADING,
        fg_color=Color.ACCENT,
        hover_color=Color.ACCENT_HOVER,
        text_color=Color.ON_ACCENT,
        corner_radius=RADIUS,
        height=36,
    )


def secondary_button_kwargs():
    return dict(
        font=Type.BODY,
        fg_color="transparent",
        hover_color=Color.CONTROL_HOVER,
        text_color=Color.TEXT,
        border_width=1,
        border_color=Color.LINE_STRONG,
        corner_radius=RADIUS,
        height=36,
    )


def ghost_button_kwargs():
    return dict(
        font=Type.BODY,
        fg_color="transparent",
        hover_color=Color.CONTROL_HOVER,
        text_color=Color.TEXT_MUTED,
        corner_radius=RADIUS_SM,
        height=32,
    )


def danger_button_kwargs():
    return dict(
        font=Type.BODY,
        fg_color="transparent",
        hover_color=Color.CONTROL_HOVER,
        text_color=Color.DANGER,
        border_width=1,
        border_color=Color.LINE_STRONG,
        corner_radius=RADIUS,
        height=36,
    )


# --------------------------------------------------------------------------
# Line icons, drawn with PIL. Rounded caps/joins give them a bit more
# character than hairline-flat. Everything is drawn inside a safe area so
# no stroke is clipped at the edges, and each icon is rendered once per size
# with BOTH a light and a dark variant baked into a single CTkImage, so
# switching appearance mode is instant and never clips or re-renders.
# --------------------------------------------------------------------------

def _hex_to_rgba(hex_color, alpha=255):
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha)


class _Pen:
    """A rounded-stroke pen over a size x size box constrained to a safe area.

    All drawer coordinates are expressed as fractions (0..1) of the usable
    area, which already excludes a margin equal to half the stroke width plus
    a small padding. That guarantees nothing is ever clipped, which was the
    cause of the cut-off music note and similar artifacts.
    """

    def __init__(self, draw, box, color, width, detail_draw=None):
        self.d = draw                      # base/color layer
        self.dd = detail_draw or draw      # detail layer (blended separately)
        self.c = color
        self.w = width
        # Safe area: keep the full stroke (plus a hair) inside the canvas.
        self.m = width * 0.6 + box * 0.04
        self.lo = self.m
        self.hi = box - self.m
        self.span = self.hi - self.lo

    def _x(self, fx):
        return self.lo + fx * self.span

    def _y(self, fy):
        return self.lo + fy * self.span

    def _r(self, f):
        return f * self.span

    def _cap(self, x, y):
        r = self.w / 2.0
        self.d.ellipse([(x - r, y - r), (x + r, y + r)], fill=self.c)

    def line(self, pts, close=False, round_ends=True):
        xy = [(self._x(fx), self._y(fy)) for fx, fy in pts]
        if close:
            xy.append(xy[0])
        self.d.line(xy, fill=self.c, width=self.w, joint="curve")
        if round_ends:
            # Round every vertex so corners and endpoints look soft, not sharp.
            for x, y in xy:
                self._cap(x, y)

    def arc(self, cx, cy, rx, ry, start, end):
        bbox = [(self._x(cx) - self._r(rx), self._y(cy) - self._r(ry)),
                (self._x(cx) + self._r(rx), self._y(cy) + self._r(ry))]
        self.d.arc(bbox, start, end, fill=self.c, width=self.w)

    def circle(self, cx, cy, r, fill=False):
        bbox = [(self._x(cx) - self._r(r), self._y(cy) - self._r(r)),
                (self._x(cx) + self._r(r), self._y(cy) + self._r(r))]
        if fill:
            self.d.ellipse(bbox, fill=self.c)
        else:
            self.d.ellipse(bbox, outline=self.c, width=self.w)

    def rrect(self, x0, y0, x1, y1, radius):
        self.d.rounded_rectangle(
            [(self._x(x0), self._y(y0)), (self._x(x1), self._y(y1))],
            radius=self._r(radius), outline=self.c, width=self.w)

    def dot(self, cx, cy, r):
        self.circle(cx, cy, r, fill=True)

    # -- Filled (solid) drawing -------------------------------------------
    # A soft, slightly-transparent white used to carve "detail" shapes out of
    # a solid silhouette. This keeps icons flat (no gradients/shadows) while
    # giving them mass, and reads well on any card background in either theme.
    _DETAIL = (255, 255, 255, 235)

    def poly(self, pts, detail=False):
        xy = [(self._x(fx), self._y(fy)) for fx, fy in pts]
        (self.dd if detail else self.d).polygon(
            xy, fill=(self._DETAIL if detail else self.c))

    def rrect_fill(self, x0, y0, x1, y1, radius, detail=False):
        (self.dd if detail else self.d).rounded_rectangle(
            [(self._x(x0), self._y(y0)), (self._x(x1), self._y(y1))],
            radius=self._r(radius), fill=(self._DETAIL if detail else self.c))

    def circle_fill(self, cx, cy, r, detail=False):
        bbox = [(self._x(cx) - self._r(r), self._y(cy) - self._r(r)),
                (self._x(cx) + self._r(r), self._y(cy) + self._r(r))]
        (self.dd if detail else self.d).ellipse(
            bbox, fill=(self._DETAIL if detail else self.c))

    def bar(self, x0, y0, x1, y1, detail=True, radius=0.02):
        # A rounded detail bar (used for document lines etc.).
        (self.dd if detail else self.d).rounded_rectangle(
            [(self._x(x0), self._y(y0)), (self._x(x1), self._y(y1))],
            radius=self._r(radius), fill=(self._DETAIL if detail else self.c))


# Each drawer receives a _Pen and draws in fractional (0..1) coordinates.
def _draw_folder(p):
    p.line([(0.04, 0.26), (0.34, 0.26), (0.42, 0.36), (0.96, 0.36),
            (0.96, 0.9), (0.04, 0.9)], close=True)


# ---- Filled content icons -------------------------------------------------
# Solid silhouettes with pale "detail" shapes carved on top. Still flat (no
# gradients or shadows), but with real mass so the grid feels less wiry.

def _draw_folder(p):
    # Solid folder with a slightly lighter front panel for a hint of depth.
    p.poly([(0.04, 0.3), (0.3, 0.3), (0.38, 0.4), (0.96, 0.4),
            (0.96, 0.9), (0.04, 0.9)])
    p.poly([(0.04, 0.22), (0.26, 0.22), (0.32, 0.3), (0.04, 0.3)])  # tab


def _draw_bucket(p):
    # Solid pail: trapezoid body + elliptical rim with a lighter inner ellipse.
    p.poly([(0.1, 0.28), (0.9, 0.28), (0.78, 0.92), (0.22, 0.92)])
    p.d.ellipse([(p._x(0.1), p._y(0.2)), (p._x(0.9), p._y(0.36))], fill=p.c)
    p.dd.ellipse([(p._x(0.22), p._y(0.23)), (p._x(0.78), p._y(0.33))], fill=p._DETAIL)


def _draw_file(p):
    p.poly([(0.16, 0.06), (0.62, 0.06), (0.84, 0.28), (0.84, 0.94), (0.16, 0.94)])
    p.poly([(0.62, 0.06), (0.62, 0.28), (0.84, 0.28)], detail=True)  # folded corner


def _draw_doc(p):
    _draw_file(p)
    for i in range(3):
        y = 0.52 + i * 0.13
        p.bar(0.3, y - 0.03, 0.7, y + 0.03)


def _draw_image(p):
    p.rrect_fill(0.08, 0.16, 0.92, 0.84, 0.12)
    p.circle_fill(0.34, 0.38, 0.09, detail=True)      # sun
    p.poly([(0.12, 0.8), (0.42, 0.52), (0.6, 0.7), (0.74, 0.56), (0.88, 0.8)], detail=True)  # hills


def _draw_audio(p):
    # Solid rounded square with a carved eighth note.
    p.rrect_fill(0.1, 0.1, 0.9, 0.9, 0.18)
    p.bar(0.58, 0.24, 0.63, 0.74, radius=0.02)        # stem
    p.poly([(0.58, 0.24), (0.82, 0.32), (0.82, 0.46), (0.58, 0.38)], detail=True)  # flag
    p.circle_fill(0.42, 0.74, 0.12, detail=True)      # note head


def _draw_video(p):
    p.rrect_fill(0.08, 0.22, 0.92, 0.78, 0.12)
    p.poly([(0.42, 0.37), (0.42, 0.63), (0.66, 0.5)], detail=True)  # play triangle


def _draw_archive(p):
    p.rrect_fill(0.22, 0.08, 0.78, 0.92, 0.1)
    for i in range(3):
        y = 0.22 + i * 0.16
        p.bar(0.44, y - 0.035, 0.56, y + 0.035, radius=0.03)  # zipper teeth


def _draw_download(p):
    p.line([(0.5, 0.1), (0.5, 0.64)])
    p.line([(0.3, 0.44), (0.5, 0.66), (0.7, 0.44)])
    p.line([(0.16, 0.9), (0.84, 0.9)])


def _draw_upload(p):
    p.line([(0.5, 0.66), (0.5, 0.12)])
    p.line([(0.3, 0.34), (0.5, 0.1), (0.7, 0.34)])
    p.line([(0.16, 0.9), (0.84, 0.9)])


def _draw_folder_plus(p):
    # Line version (this is a toolbar action, kept neutral/outline).
    p.line([(0.04, 0.26), (0.34, 0.26), (0.42, 0.36), (0.96, 0.36),
            (0.96, 0.9), (0.04, 0.9)], close=True)
    p.line([(0.38, 0.62), (0.62, 0.62)])
    p.line([(0.5, 0.5), (0.5, 0.74)])


def _draw_move(p):
    p.line([(0.1, 0.5), (0.9, 0.5)])
    p.line([(0.5, 0.1), (0.5, 0.9)])
    p.line([(0.22, 0.38), (0.1, 0.5), (0.22, 0.62)])
    p.line([(0.78, 0.38), (0.9, 0.5), (0.78, 0.62)])
    p.line([(0.38, 0.22), (0.5, 0.1), (0.62, 0.22)])
    p.line([(0.38, 0.78), (0.5, 0.9), (0.62, 0.78)])


def _draw_rename(p):
    p.line([(0.12, 0.88), (0.68, 0.32), (0.84, 0.48), (0.28, 0.88)], close=True)
    p.line([(0.6, 0.4), (0.76, 0.56)])


def _draw_trash(p):
    p.line([(0.1, 0.22), (0.9, 0.22)])
    p.line([(0.36, 0.22), (0.4, 0.1), (0.6, 0.1), (0.64, 0.22)], round_ends=False)
    p.line([(0.2, 0.22), (0.26, 0.92), (0.74, 0.92), (0.8, 0.22)])
    for dx in (-0.16, 0, 0.16):
        p.line([(0.5 + dx, 0.36), (0.5 + dx, 0.8)])


def _draw_link(p):
    p.line([(0.34, 0.66), (0.66, 0.34)])
    p.arc(0.32, 0.68, 0.22, 0.22, 20, 240)
    p.arc(0.68, 0.32, 0.22, 0.22, 200, 60)


def _draw_refresh(p):
    p.arc(0.5, 0.5, 0.38, 0.38, 60, 350)
    p.line([(0.74, 0.12), (0.9, 0.26), (0.72, 0.34)])


def _draw_key(p):
    p.circle(0.3, 0.32, 0.18)
    p.line([(0.42, 0.44), (0.88, 0.9)])
    p.line([(0.72, 0.74), (0.82, 0.64)])
    p.line([(0.82, 0.84), (0.92, 0.74)])


def _draw_logout(p):
    p.line([(0.46, 0.1), (0.14, 0.1), (0.14, 0.9), (0.46, 0.9)])
    p.line([(0.5, 0.5), (0.9, 0.5)])
    p.line([(0.72, 0.32), (0.92, 0.5), (0.72, 0.68)])


def _draw_cloud(p):
    p.arc(0.4, 0.58, 0.2, 0.2, 90, 270)
    p.arc(0.56, 0.46, 0.26, 0.26, 180, 20)
    p.line([(0.4, 0.78), (0.68, 0.78)])


def _draw_home(p):
    p.line([(0.1, 0.5), (0.5, 0.14), (0.9, 0.5)])
    p.line([(0.22, 0.42), (0.22, 0.9), (0.78, 0.9), (0.78, 0.42)])


def _draw_back(p):
    p.line([(0.62, 0.16), (0.34, 0.5), (0.62, 0.84)])


def _draw_grid(p):
    for i in range(2):
        for j in range(2):
            x = 0.1 + i * 0.5
            y = 0.1 + j * 0.5
            p.rrect(x, y, x + 0.3, y + 0.3, 0.06)


def _draw_list(p):
    for i in range(3):
        y = 0.18 + i * 0.32
        p.dot(0.12, y, 0.045)
        p.line([(0.32, y), (0.9, y)])


def _draw_sort(p):
    # Descending bars + a down arrow: "sorted, newest/top first".
    for i, w in enumerate((0.72, 0.56, 0.4, 0.26)):
        y = 0.2 + i * 0.2
        p.line([(0.1, y), (0.1 + w, y)])
    p.line([(0.86, 0.3), (0.86, 0.78)])
    p.line([(0.76, 0.66), (0.86, 0.8), (0.96, 0.66)])


_DRAWERS = {
    "sort": _draw_sort,
    "folder": _draw_folder,
    "folder_plus": _draw_folder_plus,
    "bucket": _draw_bucket,
    "file": _draw_file,
    "image": _draw_image,
    "audio": _draw_audio,
    "video": _draw_video,
    "archive": _draw_archive,
    "doc": _draw_doc,
    "download": _draw_download,
    "upload": _draw_upload,
    "move": _draw_move,
    "rename": _draw_rename,
    "trash": _draw_trash,
    "link": _draw_link,
    "refresh": _draw_refresh,
    "key": _draw_key,
    "logout": _draw_logout,
    "cloud": _draw_cloud,
    "home": _draw_home,
    "back": _draw_back,
    "grid": _draw_grid,
    "list": _draw_list,
}

# Map file extensions to an icon name.
EXT_ICON = {}
for _exts, _name in [
    (["mp3", "wav", "aac", "flac", "ogg", "m4a"], "audio"),
    (["mp4", "mov", "avi", "mkv", "webm", "flv"], "video"),
    (["jpg", "jpeg", "png", "gif", "bmp", "svg", "webp"], "image"),
    (["pdf", "doc", "docx", "txt", "md", "rtf"], "doc"),
    (["xls", "xlsx", "csv", "ppt", "pptx"], "doc"),
    (["py", "json", "xml", "js", "ts", "html", "css"], "doc"),
    (["zip", "rar", "7z", "tar", "gz"], "archive"),
]:
    for _e in _exts:
        EXT_ICON[_e] = _name


def _render(name, size, color_hex, scale):
    big = size * scale
    stroke_w = max(2, int(round(big * 0.07)))
    # Two layers: the solid color silhouette and the pale detail shapes. They
    # are composited with alpha_composite so detail blends OVER the color
    # (ImageDraw alone replaces pixels and would not blend), giving filled
    # icons real depth while staying flat.
    base = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    detail = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    pen = _Pen(ImageDraw.Draw(base), big, _hex_to_rgba(color_hex), stroke_w,
               detail_draw=ImageDraw.Draw(detail))
    _DRAWERS.get(name, _draw_file)(pen)
    # Clip the detail layer to the silhouette so it never spills outside it.
    base_alpha = base.getchannel("A")
    detail.putalpha(ImageChops.multiply(detail.getchannel("A"), base_alpha))
    base.alpha_composite(detail)
    return base.resize((size, size), Image.LANCZOS)


# Cache by (name, size, color-id). Each entry is a CTkImage holding BOTH a
# light and a dark rendering, so CustomTkinter swaps them with no work when
# the appearance mode changes.
_ICON_CACHE = {}


def icon(name, size=20, color=None, scale=4):
    """Return a theme-aware CTkImage for a named icon.

    color: a (light, dark) tuple or a single hex string.
    """
    if color is None:
        color = Color.TEXT_MUTED
    # Apply the global UI scale so every icon grows with the type.
    size = int(round(size * UI_SCALE))
    if isinstance(color, str):
        light_hex = dark_hex = color
        color_id = color
    else:
        light_hex, dark_hex = color[0], color[1]
        color_id = (light_hex, dark_hex)

    key = (name, size, color_id)
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]

    light_img = _render(name, size, light_hex, scale)
    dark_img = _render(name, size, dark_hex, scale)
    ctk_img = ctk.CTkImage(light_image=light_img, dark_image=dark_img, size=(size, size))
    _ICON_CACHE[key] = ctk_img
    return ctk_img


def ext_icon(ext, size=20, color=None):
    name = EXT_ICON.get((ext or "").lower().strip("."), "file")
    return icon(name, size=size, color=color)


def clear_icon_cache():
    """Rarely needed now that icons carry both themes; kept for safety."""
    _ICON_CACHE.clear()
