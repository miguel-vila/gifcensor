#!/usr/bin/env python3
"""Cover regions of a GIF, and check the result.

The commands split in three groups:
  look    probe, sheet, zoom, strip, colors   turn a GIF into images a vision
                                              model can read, and report how to
                                              map what it sees back to source
                                              pixel coordinates
  act     apply                               a redaction plan -> a new GIF
  check   verify                              crops of the output around every
                                              redaction edge, plus a pixel test

Only `apply` changes anything. Everything else is read-only.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)
BLOCK_FILL = "#6B6B73"   # reads as a cover on both dark and light UIs
BLOCK_EDGE = "#FF375F"   # accent border, so a cover is never mistaken for chrome
LABEL_BG = "#101010"
LABEL_FG = "#00ff66"
GRID_INK = "#ff2d95"
SHEET_BG = "#303030"


def font() -> str | None:
    return next((f for f in FONT_CANDIDATES if Path(f).exists()), None)


def run(cmd: list, stderr_ok: bool = False) -> str:
    cmd = [str(c) for c in cmd]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 and not stderr_ok:
        sys.exit(f"gifcensor: command failed:\n  {' '.join(cmd)}\n{r.stderr.strip()}")
    return r.stdout + (r.stderr if stderr_ok else "")


def emit(obj: dict) -> None:
    print(json.dumps(obj, indent=2))


# --------------------------------------------------------------------------
# boxes and frame ranges
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Box:
    x: int
    y: int
    w: int
    h: int

    @staticmethod
    def parse(s: str) -> "Box":
        parts = re.split(r"[,:x ]+", s.strip())
        if len(parts) != 4:
            sys.exit(f"gifcensor: bad box {s!r}, want x,y,w,h")
        return Box(*(int(float(p)) for p in parts))

    def inset(self, m: int) -> "Box":
        return Box(self.x + m, self.y + m, max(1, self.w - 2 * m), max(1, self.h - 2 * m))

    def grow(self, m: int, within: tuple[int, int]) -> "Box":
        x = max(0, self.x - m)
        y = max(0, self.y - m)
        return Box(x, y, min(within[0] - x, self.w + 2 * m), min(within[1] - y, self.h + 2 * m))

    def crop(self) -> str:
        return f"{self.w}x{self.h}+{self.x}+{self.y}"

    def as_list(self) -> list[int]:
        return [self.x, self.y, self.w, self.h]


def to_ranges(ns: list[int]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for n in sorted(set(ns)):
        if out and n == out[-1][1] + 1:
            out[-1] = (out[-1][0], n)
        else:
            out.append((n, n))
    return out


def select_expr(ns: list[int]) -> str:
    return "+".join(
        f"eq(n\\,{a})" if a == b else f"between(n\\,{a}\\,{b})" for a, b in to_ranges(ns)
    )


# --------------------------------------------------------------------------
# the GIF
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Gif:
    path: Path
    width: int
    height: int
    frames: int
    fps: float

    @staticmethod
    def open(path: str | Path) -> "Gif":
        p = Path(path)
        if not p.exists():
            sys.exit(f"gifcensor: no such file: {p}")
        out = run([
            "ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,nb_read_frames,avg_frame_rate",
            "-of", "json", p,
        ])
        s = json.loads(out)["streams"][0]
        num, _, den = s.get("avg_frame_rate", "0/1").partition("/")
        fps = float(num) / float(den) if float(den or 0) else 0.0
        return Gif(p, int(s["width"]), int(s["height"]), int(s["nb_read_frames"]), round(fps, 3))

    @property
    def size(self) -> tuple[int, int]:
        return (self.width, self.height)

    def info(self) -> dict:
        return {
            "file": str(self.path), "width": self.width, "height": self.height,
            "frames": self.frames, "last_frame": self.frames - 1,
            "fps": self.fps, "duration_s": round(self.frames / self.fps, 2) if self.fps else None,
        }

    def extract(self, ns: list[int], outdir: Path, box: Box | None = None) -> dict[int, Path]:
        """Decode the named frames to PNG. Keys are source frame numbers."""
        ns = sorted(set(n for n in ns if 0 <= n < self.frames))
        if not ns:
            sys.exit("gifcensor: no frames in range")
        outdir.mkdir(parents=True, exist_ok=True)
        vf = f"select='{select_expr(ns)}'"
        if box:
            vf += f",crop={box.w}:{box.h}:{box.x}:{box.y}"
        run(["ffmpeg", "-y", "-v", "error", "-i", self.path, "-vf", vf,
             "-fps_mode", "passthrough", outdir / "%05d.png"])
        files = sorted(outdir.glob("*.png"))
        if len(files) != len(ns):
            sys.exit(f"gifcensor: asked for {len(ns)} frames, decoder gave {len(files)}")
        return dict(zip(ns, files))

    def sample(self, count: int) -> list[int]:
        count = max(1, min(count, self.frames))
        step = self.frames / count
        return sorted({min(self.frames - 1, int(i * step)) for i in range(count)})


# --------------------------------------------------------------------------
# image helpers (ImageMagick)
# --------------------------------------------------------------------------

def labelled(src: Path, text: str, dst: Path, scale_pct: int | None = None,
             side: str = "left", lw: int = 78) -> Path:
    """Put a frame number next to a frame, so a reader never has to count."""
    f = font()
    pre = ["magick"]
    img = [str(src)] + (["-scale", f"{scale_pct}%"] if scale_pct else [])
    if not f:
        run(pre + img + [str(dst)])
        return dst
    lab = ["-background", LABEL_BG, "-fill", LABEL_FG, "-font", f, "-pointsize", "18"]
    if side == "left":
        lab += ["-size", f"{lw}x", "-gravity", "center", f"label:{text}"]
        run(pre + lab + img + ["-background", LABEL_BG, "-gravity", "center", "+append", str(dst)])
    else:
        lab += ["-gravity", "west", f"label:{text}"]
        run(pre + img + lab + ["-background", LABEL_BG, "-gravity", "west",
                               "-splice", "0x0", "-append", str(dst)])
    return dst


def pixel_colors(img: Path, points: list[tuple[int, int]]) -> list[str]:
    fmt = "".join("%%[pixel:p{%d,%d}]\n" % p for p in points)
    out = run(["magick", img, "-format", fmt, "info:"])
    return [normalise_color(v) for v in out.strip().splitlines() if v.strip()]


def normalise_color(v: str) -> str:
    v = v.strip()
    m = re.match(r"s?rgba?\((\d+)[,\s]+(\d+)[,\s]+(\d+)", v)
    if m:
        return "#%02X%02X%02X" % tuple(int(g) for g in m.groups())
    m = re.match(r"#([0-9A-Fa-f]{6})", v)
    if m:
        return "#" + m.group(1).upper()
    out = run(["magick", "-size", "1x1", f"xc:{v}", "-format", "%[hex:u.p{0,0}]", "info:"])
    return "#" + out.strip()[:6].upper()


def crop_to(src: Path, box: Box, dst: Path) -> Path:
    run(["magick", src, "-crop", box.crop(), "+repage", str(dst)])
    return dst


def crop_stats(img: Path, box: Box) -> float:
    """Normalised standard deviation of a region. 0 means one flat colour."""
    out = run(["magick", img, "-crop", box.crop(), "+repage",
               "-format", "%[fx:standard_deviation]", "info:"])
    try:
        return round(float(out.strip().split()[0]), 5)
    except (ValueError, IndexError):
        return -1.0


def rmse(a: Path, b: Path) -> float:
    out = run(["magick", "compare", "-metric", "RMSE", a, b, "null:"], stderr_ok=True)
    m = re.search(r"\(([\d.eE+-]+)\)", out)
    return round(float(m.group(1)), 5) if m else -1.0


def grid_overlay(img: Path, dst: Path, origin: tuple[int, int], scale: float,
                 step: int | None = None) -> int:
    """Draw source-pixel coordinate lines over a zoomed crop."""
    w, h = (int(v) for v in run(["magick", img, "-format", "%w %h", "info:"]).split())
    src_w, src_h = w / scale, h / scale
    if step is None:
        raw = max(src_w, src_h) / 8
        step = next((s for s in (5, 10, 20, 25, 50, 100, 200, 250, 500) if s >= raw), 1000)
    f = font()
    draw: list[str] = []
    ox, oy = origin
    sx = ox - ox % step + step
    while sx < ox + src_w:
        x = (sx - ox) * scale
        draw += ["-draw", f"line {x},0 {x},{h}"]
        sx += step
    sy = oy - oy % step + step
    while sy < oy + src_h:
        y = (sy - oy) * scale
        draw += ["-draw", f"line 0,{y} {w},{y}"]
        sy += step
    cmd = ["magick", img, "-stroke", GRID_INK, "-strokewidth", "1", "-fill", "none"] + draw
    if f:
        cmd += ["-stroke", "none", "-fill", GRID_INK, "-font", f, "-pointsize", "15"]
        sx = ox - ox % step + step
        while sx < ox + src_w:
            cmd += ["-annotate", "+%d+%d" % ((sx - ox) * scale + 3, 16), str(sx)]
            sx += step
        sy = oy - oy % step + step
        while sy < oy + src_h:
            cmd += ["-annotate", "+%d+%d" % (3, (sy - oy) * scale - 4), str(sy)]
            sy += step
    run(cmd + [str(dst)])
    return step


# --------------------------------------------------------------------------
# the plan
# --------------------------------------------------------------------------

@dataclass
class Redaction:
    label: str
    box: Box
    ranges: list[tuple[int, int]] | None  # None means every frame
    color: str  # "#RRGGBB" or "auto"
    style: str  # "block": a visible cover; "blend": take the colour around it

    def enable(self) -> str | None:
        if self.ranges is None:
            return None
        return "+".join(f"between(n\\,{a}\\,{b})" for a, b in self.ranges)

    def sample_frames(self, last: int) -> list[tuple[int, str]]:
        """Frames worth looking at: inside each range, and just outside it."""
        spans = self.ranges if self.ranges is not None else [(0, last)]
        out: list[tuple[int, str]] = []
        for a, b in spans:
            if a - 1 >= 0:
                out.append((a - 1, "before"))
            out += [(a, "in"), ((a + b) // 2, "in"), (b, "in")]
            if b + 1 <= last:
                out.append((b + 1, "after"))
        seen: dict[int, str] = {}
        for n, kind in out:
            if seen.get(n) != "in":
                seen[n] = kind
        return sorted(seen.items())


@dataclass
class Plan:
    source: Path
    output: Path
    redactions: list[Redaction]

    @staticmethod
    def load(path: str | Path, output_override: str | None = None) -> "Plan":
        p = Path(path)
        d = json.loads(p.read_text())
        base = p.parent
        src = (base / d["source"]).resolve() if not Path(d["source"]).is_absolute() else Path(d["source"])
        out = output_override or d.get("output") or str(src.with_name(src.stem + " (censored)" + src.suffix))
        out_p = Path(out) if Path(out).is_absolute() else (base / out).resolve()
        reds = []
        default_style = d.get("style", "block")
        for i, r in enumerate(d.get("redactions", [])):
            if "box" not in r:
                sys.exit(f"gifcensor: redaction {i} has no box")
            bx = r["box"]
            box = Box(*bx) if isinstance(bx, list) else Box.parse(bx)
            fr = r.get("frames", "all")
            ranges = None if fr in ("all", None) else [tuple(int(v) for v in pair) for pair in fr]
            style = r.get("style", default_style)
            if style not in ("block", "blend"):
                sys.exit(f"gifcensor: redaction {i}: style must be block or blend")
            reds.append(Redaction(r.get("label", f"redaction {i}"), box, ranges,
                                  r.get("color", "auto"), style))
        if not reds:
            sys.exit("gifcensor: plan has no redactions")
        return Plan(src, out_p, reds)


def resolve_color(gif: Gif, red: Redaction, work: Path) -> str:
    """The fill. A block cover is deliberately loud; a blend takes the colour
    of the chrome around the box so the cover reads as part of the UI."""
    if red.color != "auto":
        return normalise_color(red.color)
    if red.style == "block":
        return BLOCK_FILL
    a = red.ranges[0][0] if red.ranges else 0
    b = red.ranges[0][1] if red.ranges else gif.frames - 1
    n = (a + b) // 2
    frame = gif.extract([n], work / f"c{n}")[n]
    bx = red.box
    pad = 5
    pts: list[tuple[int, int]] = []
    for t in (0.15, 0.5, 0.85):
        pts += [
            (int(bx.x + bx.w * t), bx.y - pad), (int(bx.x + bx.w * t), bx.y + bx.h + pad),
            (bx.x - pad, int(bx.y + bx.h * t)), (bx.x + bx.w + pad, int(bx.y + bx.h * t)),
        ]
    pts = [(min(max(x, 0), gif.width - 1), min(max(y, 0), gif.height - 1)) for x, y in pts]
    return Counter(pixel_colors(frame, pts)).most_common(1)[0][0]


def filter_graph(plan: Plan, colors: list[str]) -> str:
    lines = ["[0:v]"]
    for red, col in zip(plan.redactions, colors):
        bx = red.box
        en = red.enable()
        strokes = [(col, "fill")] + ([(BLOCK_EDGE, "2")] if red.style == "block" else [])
        for ink, thickness in strokes:
            part = (f"drawbox=x={bx.x}:y={bx.y}:w={bx.w}:h={bx.h}"
                    f":color=0x{ink.lstrip('#')}@1:t={thickness}")
            if en:
                part += f":enable='{en}'"
            lines.append(part + ",")
    lines += [
        "split[a][b];",
        "[a]palettegen=stats_mode=diff[p];",
        "[b][p]paletteuse=dither=bayer:bayer_scale=3:diff_mode=rectangle",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------

def cmd_probe(a) -> None:
    emit(Gif.open(a.gif).info())


def cmd_sheet(a) -> None:
    gif = Gif.open(a.gif)
    ns = gif.sample(a.count)
    scale = min(1.0, a.tile_width / gif.width)
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        files = gif.extract(ns, work / "f")
        tiles = []
        for n, f in files.items():
            tiles.append(labelled(f, str(n), work / f"t{n:05d}.png",
                                  scale_pct=int(scale * 100), side="bottom"))
        out = Path(a.out)
        f = font()
        run(["magick", "montage"] + (["-font", f] if f else []) + [str(t) for t in tiles] +
            ["-tile", f"{a.cols}x", "-geometry", "+3+3", "-background", SHEET_BG, str(out)])
    emit({
        "image": str(Path(a.out).resolve()), "frames_shown": ns, "cols": a.cols,
        "scale": round(scale, 4),
        "note": "Each tile carries its frame number below it. A point (tx,ty) inside "
                "a tile maps to source (tx/scale, ty/scale). Use `zoom` before trusting "
                "any coordinate read off this sheet.",
    })


def cmd_zoom(a) -> None:
    gif = Gif.open(a.gif)
    box = Box.parse(a.box) if a.box else Box(0, 0, gif.width, gif.height)
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        frame = gif.extract([a.frame], work / "f", box=box)[a.frame]
        scale = a.scale or min(8.0, max(1.0, round(a.target_width / box.w, 2)))
        out = Path(a.out)
        run(["magick", frame, "-filter", "point", "-resize", f"{scale * 100}%", str(out)])
        step = grid_overlay(out, out, (box.x, box.y), scale) if a.grid else None
    emit({
        "image": str(Path(a.out).resolve()), "frame": a.frame, "box": box.as_list(),
        "scale": scale, "grid_step_px": step,
        "note": f"Pink lines are source coordinates. Image point (ix,iy) maps to source "
                f"({box.x} + ix/{scale}, {box.y} + iy/{scale}).",
    })


def cmd_strip(a) -> None:
    gif = Gif.open(a.gif)
    box = Box.parse(a.box)
    first, last = (int(v) for v in a.frames.split(":"))
    last = min(last, gif.frames - 1)
    step = a.step or max(1, round((last - first + 1) / (a.max_rows * a.cols)))
    ns = list(range(first, last + 1, step))
    scale = min(1.0, a.row_width / box.w)
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        files = gif.extract(ns, work / "f", box=box)
        rows = [labelled(f, str(n), work / f"r{n:05d}.png", scale_pct=int(scale * 100))
                for n, f in files.items()]
        chunks = [rows[i:i + a.max_rows] for i in range(0, len(rows), a.max_rows)]
        cols = []
        for i, ch in enumerate(chunks):
            c = work / f"c{i}.png"
            run(["magick"] + [str(x) for x in ch] +
                ["-background", "#ff0000", "-splice", "0x1", "-append", str(c)])
            cols.append(c)
        run(["magick"] + [str(c) for c in cols] +
            ["-background", SHEET_BG, "-gravity", "north", "-splice", "6x0", "+append", str(a.out)])
    emit({
        "image": str(Path(a.out).resolve()), "box": box.as_list(), "frames_shown": ns,
        "step": step, "columns": len(cols), "scale": round(scale, 4),
        "note": "One row per frame, frame number on the left, columns read top-to-bottom "
                "then left-to-right. Use this to find the exact frame a thing appears "
                "and disappears.",
    })


def cmd_colors(a) -> None:
    gif = Gif.open(a.gif)
    pts = [tuple(int(v) for v in p.split(",")) for p in a.at]
    with tempfile.TemporaryDirectory() as td:
        frame = gif.extract([a.frame], Path(td))[a.frame]
        cols = pixel_colors(frame, pts)
    emit({"frame": a.frame, "colors": [{"at": list(p), "hex": c} for p, c in zip(pts, cols)]})


def cmd_apply(a) -> None:
    plan = Plan.load(a.plan, a.out)
    gif = Gif.open(plan.source)
    for red in plan.redactions:
        if red.ranges:
            for lo, hi in red.ranges:
                if not (0 <= lo <= hi < gif.frames):
                    sys.exit(f"gifcensor: {red.label!r}: range [{lo},{hi}] outside "
                             f"0..{gif.frames - 1}")
        b = red.box
        if b.x < 0 or b.y < 0 or b.x + b.w > gif.width or b.y + b.h > gif.height:
            sys.exit(f"gifcensor: {red.label!r}: box {b.as_list()} outside {gif.size}")
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        colors = [resolve_color(gif, r, work) for r in plan.redactions]
        graph = filter_graph(plan, colors)
        if a.dry_run:
            print(graph)
            return
        fpath = work / "filter.txt"
        fpath.write_text(graph)
        run(["ffmpeg", "-y", "-v", "error", "-i", gif.path, "-/filter_complex", fpath,
             "-loop", "0", plan.output])
    out = Gif.open(plan.output)
    emit({
        "output": str(plan.output), "frames": out.frames, "size": list(out.size),
        "bytes": plan.output.stat().st_size, "source_bytes": gif.path.stat().st_size,
        "redactions": [
            {"label": r.label, "box": r.box.as_list(), "color": c, "style": r.style,
             "frames": "all" if r.ranges is None else [list(p) for p in r.ranges]}
            for r, c in zip(plan.redactions, colors)
        ],
    })


def cmd_verify(a) -> None:
    plan = Plan.load(a.plan, a.out_gif)
    if not plan.output.exists():
        sys.exit(f"gifcensor: {plan.output} does not exist. Run `apply` first.")
    src, out = Gif.open(plan.source), Gif.open(plan.output)
    outdir = Path(a.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    report = []
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        sampled = [red.sample_frames(out.frames - 1) for red in plan.redactions]
        every = sorted({n for w in sampled for n, _ in w})
        o_full = out.extract(every, work / "o")
        s_full = src.extract(every, work / "s")
        for i, (red, wanted) in enumerate(zip(plan.redactions, sampled)):
            view = red.box.grow(a.margin, out.size)
            o_crop = {n: crop_to(o_full[n], view, work / f"oc{i}_{n:05d}.png")
                      for n, _ in wanted}
            checks, rows = [], []
            inner = red.box.inset(3) if red.style == "block" else red.box
            for n, kind in wanted:
                flat = crop_stats(o_full[n], inner)
                changed = rmse(o_full[n], s_full[n])
                checks.append({"frame": n, "position": kind,
                               "box_flatness": flat, "differs_from_source": changed,
                               "covered": kind != "in" or (flat <= a.flat_threshold and changed > 0)})
                rows.append(labelled(o_crop[n], f"{n}\n{kind}", work / f"v{i}_{n:05d}.png"))
            img = outdir / f"{i:02d}_{re.sub(r'[^a-z0-9]+', '_', red.label.lower())}.png"
            run(["magick"] + [str(r) for r in rows] +
                ["-background", "#ff0000", "-splice", "0x1", "-append", str(img)])
            report.append({
                "label": red.label, "box": red.box.as_list(),
                "frames": "all" if red.ranges is None else [list(p) for p in red.ranges],
                "image": str(img.resolve()), "checks": checks,
                "machine_pass": all(c["covered"] for c in checks),
            })
    emit({
        "output": str(plan.output), "machine_pass": all(r["machine_pass"] for r in report),
        "redactions": report,
        "note": "machine_pass only says the box is one flat colour and differs from the "
                "source. Look at every image: rows marked `before`/`after` must not show "
                "the secret either, and the whole output still needs a `sheet` pass for "
                "anything the plan missed.",
    })


def main() -> None:
    p = argparse.ArgumentParser(prog="gifcensor", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("probe", help="size, frame count, fps")
    s.add_argument("gif")
    s.set_defaults(fn=cmd_probe)

    s = sub.add_parser("sheet", help="contact sheet of numbered frames")
    s.add_argument("gif")
    s.add_argument("-o", "--out", required=True)
    s.add_argument("--count", type=int, default=21)
    s.add_argument("--cols", type=int, default=3)
    s.add_argument("--tile-width", type=int, default=470)
    s.set_defaults(fn=cmd_sheet)

    s = sub.add_parser("zoom", help="one frame, cropped and magnified, with a coordinate grid")
    s.add_argument("gif")
    s.add_argument("-o", "--out", required=True)
    s.add_argument("--frame", type=int, required=True)
    s.add_argument("--box", help="x,y,w,h in source pixels (default: whole frame)")
    s.add_argument("--scale", type=float, default=None)
    s.add_argument("--target-width", type=int, default=1200)
    s.add_argument("--grid", action=argparse.BooleanOptionalAction, default=True)
    s.set_defaults(fn=cmd_zoom)

    s = sub.add_parser("strip", help="one region across a frame range, to find exact boundaries")
    s.add_argument("gif")
    s.add_argument("-o", "--out", required=True)
    s.add_argument("--box", required=True, help="x,y,w,h")
    s.add_argument("--frames", required=True, help="first:last")
    s.add_argument("--step", type=int, default=None)
    s.add_argument("--max-rows", type=int, default=18)
    s.add_argument("--cols", type=int, default=3)
    s.add_argument("--row-width", type=int, default=560)
    s.set_defaults(fn=cmd_strip)

    s = sub.add_parser("colors", help="pixel colours at points of a frame")
    s.add_argument("gif")
    s.add_argument("--frame", type=int, required=True)
    s.add_argument("--at", action="append", required=True, metavar="X,Y")
    s.set_defaults(fn=cmd_colors)

    s = sub.add_parser("apply", help="plan -> censored GIF")
    s.add_argument("plan")
    s.add_argument("-o", "--out", default=None, help="override the plan's output path")
    s.add_argument("--dry-run", action="store_true", help="print the ffmpeg filter graph")
    s.set_defaults(fn=cmd_apply)

    s = sub.add_parser("verify", help="check the output against the plan")
    s.add_argument("plan")
    s.add_argument("--outdir", required=True)
    s.add_argument("--out-gif", default=None)
    s.add_argument("--margin", type=int, default=40)
    s.add_argument("--flat-threshold", type=float, default=0.03)
    s.set_defaults(fn=cmd_verify)

    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
