"""Re-draw the Chinese text baked into client images, in English.

The table is localise/images.toml (reviewed by hand, committed): one entry per
image with the Chinese text, the English text and where the text sits. For
each entry the stock PNG is read from .stock (never written), the Chinese
glyphs are removed and the English is drawn in its place, and the result is
written under the English overlay (git-ignored), mirroring the stock path:

  data/en/assets/res/assets/<path>.png

client.build_assets copies that tree over the stock assets, the same way it
ships the English language files. Same pixel size as the original; pixels
outside the entry's erase box are left exactly as they were.

How the Chinese goes:
  mode "clear"    the text pixels in the box become transparent (images that
                  are only text, or text floating beside a plate);
  mode "inpaint"  the text pixels are filled in from the surrounding plate.
Which pixels are text ("mask"):
  "all"     every pixel in the box;
  "light"   pixels brighter than `light` on all three channels (white glyphs);
  "lum"     pixels whose luminance is at least `light` (coloured glyphs on a
            dark plate);
  "color"   pixels within `tol` of `color` (coloured glyphs);
  "opaque"  pixels with alpha above 0 (pure text images);
grown by `grow` pixels so the glyph outline goes too.

The English is drawn with Lilita One (SIL OFL 1.1, localise/fonts), a
vertical gradient fill, an outline, and an optional glow and drop shadow.
Colours not given in the table are sampled from the original glyphs. The
size is the largest that fits the text box, on one line or split on a space
onto two.

Run:  py -3.14 -m localise.images              (render into data/en)
      py -3.14 -m localise.images --sheets DIR (also before/after sheets)
"""

from __future__ import annotations

import argparse
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
TABLE = HERE / "images.toml"
FONT = HERE / "fonts/LilitaOne-Regular.ttf"
STOCK_ASSETS = Path("assets/res/assets")
EN_DIR = Path("data/en")
MIN_SIZE = 7
SHEET_PAGE = 24


@dataclass
class Entry:
    path: str
    zh: str
    en: str
    group: str
    mode: str = "inpaint"
    mask: str = "all"
    # x0, y0, x1, y1 (exclusive), or a list of such boxes; None = whole image
    erase: list | None = None
    text: list[int] | None = None  # where the English goes; None = erase box
    light: int = 200
    color: str | None = None
    tol: int = 60
    grow: int = 2
    fill: list[str] | None = None  # [top, bottom] of the gradient
    outline: str | None = None
    stroke: float = 0.12  # outline width as a fraction of the font size
    glow: str | None = None  # colour, or "auto" to sample it
    glow_radius: int = 0
    shadow: int = 0  # drop shadow offset in px, 0 = none
    max_size: int = 0  # 0 = no cap
    lines: int = 2  # most lines the text may use
    rotate: int = 0  # degrees counter-clockwise (vertical labels)
    # More English pieces in other places of the same image, each a table
    # with `en` and `text` and optionally its own fill/outline/glow/...
    parts: list[dict] = field(default_factory=list)


# --- the table -------------------------------------------------------------------


def load_table(path: Path = TABLE) -> list[Entry]:
    """Entries of the table, each with its preset's keys under its own."""
    cfg = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    presets = cfg.get("preset", {})
    known = set(Entry.__dataclass_fields__)
    out = []
    for raw in cfg["image"]:
        merged = dict(presets.get(raw.get("preset", ""), {}))
        merged.update({k: v for k, v in raw.items() if k != "preset"})
        unknown = set(merged) - known
        if unknown:
            raise ValueError(f"{raw.get('path')}: unknown keys {sorted(unknown)}")
        out.append(Entry(**merged))
    paths = [e.path for e in out]
    dupes = {p for p in paths if paths.count(p) > 1}
    if dupes:
        raise ValueError(f"duplicate paths in the table: {sorted(dupes)}")
    return out


# --- erasing ---------------------------------------------------------------------


def _box(entry_box: list[int] | None, w: int, h: int) -> tuple[int, int, int, int]:
    if entry_box is None:
        return 0, 0, w, h
    x0, y0, x1, y1 = entry_box
    return max(0, x0), max(0, y0), min(w, x1), min(h, y1)


def _hex(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def text_mask(rgba: np.ndarray, e: Entry) -> np.ndarray:
    """Boolean HxW: the Chinese text pixels (with their outline) inside the box."""
    h, w = rgba.shape[:2]
    rgb = rgba[..., :3].astype(int)
    alpha = rgba[..., 3]
    if e.mask == "all":
        core = np.ones((h, w), bool)
    elif e.mask == "opaque":
        core = alpha > 0
    elif e.mask == "light":
        core = (rgb.min(axis=2) >= e.light) & (alpha > 128)
    elif e.mask == "lum":
        core = (_lum(rgb) >= e.light) & (alpha > 128)
    elif e.mask == "color":
        ref = np.array(_hex(e.color))
        core = (np.abs(rgb - ref).max(axis=2) <= e.tol) & (alpha > 128)
    else:
        raise ValueError(f"{e.path}: unknown mask {e.mask!r}")
    inbox = np.zeros((h, w), bool)
    boxes = e.erase if e.erase and isinstance(e.erase[0], list) else [e.erase]
    for b in boxes:
        x0, y0, x1, y1 = _box(b, w, h)
        inbox[y0:y1, x0:x1] = True
    core &= inbox
    if e.grow > 0 and e.mask not in ("all", "opaque"):
        m = Image.fromarray(core.astype(np.uint8) * 255).filter(
            ImageFilter.MaxFilter(2 * e.grow + 1))
        core = (np.asarray(m) > 0) & inbox
    return core


def inpaint(rgba: np.ndarray, mask: np.ndarray, smooth: int = 40) -> np.ndarray:
    """Fill the masked pixels from their neighbours (onion peel, then smoothing).

    Works on premultiplied colour so transparent neighbours do not bleed
    black into the fill.
    """
    a = rgba.astype(np.float64)
    pm = a.copy()
    pm[..., :3] *= a[..., 3:4] / 255.0
    known = ~mask
    h, w = mask.shape
    shifts = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]

    def neighbours(arr, ok):
        acc = np.zeros_like(arr)
        cnt = np.zeros((h, w))
        pa = np.pad(arr, ((1, 1), (1, 1), (0, 0)))
        pk = np.pad(ok, 1)
        for dy, dx in shifts:
            k = pk[1 + dy:1 + dy + h, 1 + dx:1 + dx + w]
            acc += pa[1 + dy:1 + dy + h, 1 + dx:1 + dx + w] * k[..., None]
            cnt += k
        return acc, cnt

    while not known.all():
        acc, cnt = neighbours(pm, known)
        new = ~known & (cnt > 0)
        if not new.any():
            break
        pm[new] = acc[new] / cnt[new][:, None]
        known |= new
    everywhere = np.ones((h, w), bool)
    for _ in range(smooth):
        acc, cnt = neighbours(pm, everywhere)
        pm[mask] = acc[mask] / cnt[mask][:, None]
    out = pm.copy()
    al = np.clip(pm[..., 3:4], 1e-6, 255)
    out[..., :3] = np.where(pm[..., 3:4] > 0.5, pm[..., :3] * 255.0 / al, 0)
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)


# --- colours ---------------------------------------------------------------------


def _lum(rgb: np.ndarray) -> np.ndarray:
    return rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114


def _css(c) -> str:
    return "#%02x%02x%02x" % tuple(int(round(v)) for v in c[:3])


def sample_style(rgba: np.ndarray, mask: np.ndarray) -> dict:
    """Fill gradient, outline and glow colours of the original glyphs."""
    ys, xs = np.nonzero(mask & (rgba[..., 3] > 200))
    if len(ys) < 4:
        return {"fill": ["#ffffff", "#ffffff"], "outline": "#3a2010", "glow": "#ffd860"}
    px = rgba[ys, xs, :3].astype(float)
    lum = _lum(px)
    hi = lum >= np.percentile(lum, 65)
    lo = lum <= np.percentile(lum, 15)
    mid = np.median(ys[hi])
    top = px[hi & (ys <= mid)]
    bot = px[hi & (ys > mid)]
    top = top.mean(axis=0) if len(top) else px[hi].mean(axis=0)
    bot = bot.mean(axis=0) if len(bot) else top
    outline = px[lo].mean(axis=0) * 0.85
    soft = mask & (rgba[..., 3] > 20) & (rgba[..., 3] < 170)
    gys, gxs = np.nonzero(soft)
    glow = rgba[gys, gxs, :3].astype(float).mean(axis=0) if len(gys) else top
    return {"fill": [_css(top), _css(bot)], "outline": _css(outline), "glow": _css(glow)}


# --- drawing ---------------------------------------------------------------------


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT), size)


def _stroke(e: Entry, size: int) -> int:
    return max(1, round(size * e.stroke)) if e.stroke > 0 else 0


def _block(lines: list[str], size: int, stroke: int) -> tuple[int, int, int]:
    """(width, height, line step) of the inked block of lines."""
    f = _font(size)
    step = round(size * 0.92)
    widths, top, bottom = [], None, None
    for i, line in enumerate(lines):
        x0, y0, x1, y1 = f.getbbox(line, anchor="ls", stroke_width=stroke)
        widths.append(x1 - x0)
        y0 += i * step
        y1 += i * step
        top = y0 if top is None else min(top, y0)
        bottom = y1 if bottom is None else max(bottom, y1)
    return max(widths), bottom - top, step


def layout(text: str, e: Entry, box_w: int, box_h: int) -> tuple[list[str], int]:
    """Lines and font size: the largest size whose block fits the box."""
    if "\n" in text:
        options = [text.split("\n")]
    else:
        words = text.split(" ")
        options = [[text]]
        if e.lines >= 2:
            options += [[" ".join(words[:i]), " ".join(words[i:])] for i in range(1, len(words))]
    best: tuple[int, int, list[str]] | None = None
    cap = e.max_size or 200
    for lines in options:
        lo, hi = MIN_SIZE, cap
        if not _fits(lines, lo, e, box_w, box_h):
            size = MIN_SIZE
        else:
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if _fits(lines, mid, e, box_w, box_h):
                    lo = mid
                else:
                    hi = mid - 1
            size = lo
        key = (size, -len(lines))
        if best is None or key > best[:2]:
            best = (size, -len(lines), lines)
    return best[2], best[0]


def _fits(lines, size, e, box_w, box_h) -> bool:
    w, h, _ = _block(lines, size, _stroke(e, size))
    return w <= box_w and h <= box_h


def draw_text(img: Image.Image, e: Entry, style: dict, box) -> Image.Image:
    """Draw e.en centred in box onto img (RGBA), returns the new image."""
    if not e.en:
        return img
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0
    if e.rotate in (90, 270):
        bw, bh = bh, bw
    lines, size = layout(e.en, e, bw, bh)
    stroke = _stroke(e, size)
    f = _font(size)
    w, h, step = _block(lines, size, stroke)
    pad = stroke + e.glow_radius * 2 + e.shadow + 4
    cw, ch = w + 2 * pad, h + 2 * pad
    fill_m = Image.new("L", (cw, ch))
    stroke_m = Image.new("L", (cw, ch))
    df, ds = ImageDraw.Draw(fill_m), ImageDraw.Draw(stroke_m)
    # baseline of the first line so that the block's ink starts at pad
    top0 = min(f.getbbox(line, anchor="ls", stroke_width=stroke)[1] + i * step
               for i, line in enumerate(lines))
    for i, line in enumerate(lines):
        y = pad - top0 + i * step
        df.text((cw / 2, y), line, font=f, anchor="ms", fill=255)
        ds.text((cw / 2, y), line, font=f, anchor="ms", fill=255,
                stroke_width=stroke, stroke_fill=255)
    fill = e.fill or style["fill"]
    top_c, bot_c = np.array(_hex(fill[0]), float), np.array(_hex(fill[-1]), float)
    bb = fill_m.getbbox() or (0, 0, cw, ch)
    t = np.clip((np.arange(ch)[:, None] - bb[1]) / max(1, bb[3] - bb[1] - 1), 0, 1)
    grad = (top_c[None, None, :] * (1 - t[..., None]) + bot_c[None, None, :] * t[..., None])
    grad = np.broadcast_to(grad, (ch, cw, 3))
    layer = Image.new("RGBA", (cw, ch))
    if e.glow:
        gc = _hex(style["glow"] if e.glow == "auto" else e.glow)
        r = max(1, e.glow_radius or max(2, size // 6))
        g = stroke_m.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.GaussianBlur(r))
        g = g.point(lambda v: min(255, int(v * 1.6)))
        layer.alpha_composite(Image.merge("RGBA", (*[Image.new("L", (cw, ch), c) for c in gc], g)))
    outline = _hex(e.outline or style["outline"])
    if e.shadow:
        sh = Image.new("L", (cw, ch))
        sh.paste(stroke_m, (e.shadow, e.shadow))
        dark = tuple(int(c * 0.5) for c in outline)
        layer.alpha_composite(Image.merge("RGBA", (*[Image.new("L", (cw, ch), c) for c in dark], sh)))
    if stroke:
        layer.alpha_composite(
            Image.merge("RGBA", (*[Image.new("L", (cw, ch), c) for c in outline], stroke_m)))
    rgb = Image.fromarray(np.ascontiguousarray(grad).astype(np.uint8), "RGB")
    layer.alpha_composite(Image.merge("RGBA", (*rgb.split(), fill_m)))
    if e.rotate:
        layer = layer.rotate(e.rotate, expand=True, resample=Image.BICUBIC)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    out = img.copy()
    out.alpha_composite(layer, (round(cx - layer.width / 2), round(cy - layer.height / 2)))
    return out


def render(e: Entry, stock_assets: Path) -> Image.Image:
    src = Image.open(stock_assets / e.path)
    img = src.convert("RGBA")
    rgba = np.asarray(img).copy()
    mask = text_mask(rgba, e)
    style = sample_style(rgba, mask)
    if e.mode == "clear":
        rgba[mask] = 0
    elif e.mode == "inpaint":
        rgba = inpaint(rgba, mask)
    else:
        raise ValueError(f"{e.path}: unknown mode {e.mode!r}")
    base = Image.fromarray(rgba, "RGBA")
    if not e.en and not e.parts:
        return base
    h, w = rgba.shape[:2]
    if e.text is None and e.erase and isinstance(e.erase[0], list):
        raise ValueError(f"{e.path}: several erase boxes need an explicit text box")
    out = draw_text(base, e, style, _box(e.text or e.erase, w, h))
    for part in e.parts:
        pe = replace(e, parts=[], **part)
        out = draw_text(out, pe, style, _box(pe.text, w, h))
    # Nothing may be drawn outside the image; alpha_composite already clips.
    assert out.size == src.size
    return out


def build(stock: Path, out: Path = EN_DIR, table: Path = TABLE) -> list[Entry]:
    entries = load_table(table)
    src_root = Path(stock) / STOCK_ASSETS
    dst_root = Path(out) / STOCK_ASSETS
    for e in entries:
        dst = dst_root / e.path
        dst.parent.mkdir(parents=True, exist_ok=True)
        render(e, src_root).save(dst, optimize=True)
    return entries


# --- review sheets ---------------------------------------------------------------


def contact_sheets(entries: list[Entry], stock: Path, out: Path, sheet_dir: Path) -> list[Path]:
    """JPEGs per group (24 images each): stock on the left, English on the right."""
    sheet_dir.mkdir(parents=True, exist_ok=True)
    groups: dict[str, list[Entry]] = {}
    for e in entries:
        groups.setdefault(e.group, []).append(e)
    written = []
    label_font = ImageFont.truetype(str(FONT), 13)
    pages = []
    for group, items in groups.items():
        chunks = [items[i:i + SHEET_PAGE] for i in range(0, len(items), SHEET_PAGE)]
        for n, chunk in enumerate(chunks, 1):
            pages.append((group if len(chunks) == 1 else f"{group}-{n}", chunk))
    for name, items in pages:
        cells = []
        for e in items:
            a = Image.open(Path(stock) / STOCK_ASSETS / e.path).convert("RGBA")
            b = Image.open(Path(out) / STOCK_ASSETS / e.path).convert("RGBA")
            s = min(2.0, 330 / a.width, 170 / a.height)
            size = (max(1, round(a.width * s)), max(1, round(a.height * s)))
            cells.append((e, a.resize(size, Image.LANCZOS), b.resize(size, Image.LANCZOS)))
        cw = max(2 * c[1].width + 24 for c in cells)
        cw = max(cw, 260)
        ch = max(c[1].height for c in cells) + 22
        cols = max(1, 1900 // cw)
        rows = (len(cells) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * cw, rows * ch), (58, 66, 58))
        d = ImageDraw.Draw(sheet)
        for k, (e, a, b) in enumerate(cells):
            x, y = (k % cols) * cw, (k // cols) * ch
            sheet.paste(a, (x + 4, y + 2), a)
            sheet.paste(b, (x + 12 + a.width, y + 2), b)
            d.text((x + 4, y + ch - 18), f"{Path(e.path).name}: {e.en}"[:48],
                   font=label_font, fill=(255, 235, 90))
        dst = sheet_dir / f"{name}.jpg"
        sheet.save(dst, quality=85)
        written.append(dst)
    return written


def main(argv: list[str] | None = None) -> int:
    from server.settings import load as load_settings

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, default=Path("settings.toml"))
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--table", type=Path, default=TABLE)
    parser.add_argument("--sheets", type=Path, default=None)
    args = parser.parse_args(argv)
    s = load_settings(args.settings)
    out = args.out or s.english_dir or EN_DIR
    entries = build(s.stock_dir, out, args.table)
    counts: dict[str, int] = {}
    for e in entries:
        counts[e.group] = counts.get(e.group, 0) + 1
    print(f"{len(entries)} images in English under {out / STOCK_ASSETS}: "
          + ", ".join(f"{g} {n}" for g, n in counts.items()))
    if args.sheets:
        for p in contact_sheets(entries, s.stock_dir, out, args.sheets):
            print(f"sheet {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
