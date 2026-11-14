# gifcensor

Cover private regions of a GIF screen recording, and check that the cover holds.

Finding *what* to censor needs a pair of eyes. Applying and checking it does
not. This tool is the deterministic half: it turns a GIF into images a vision
model can read precisely, applies a redaction plan, and checks the result. The
AI half lives in `skill/SKILL.md`, which drives it.

    python3 -I gifcensor.py --help

| group | command | purpose |
|---|---|---|
| look | `probe` | size, frame count, fps |
| look | `sheet` | contact sheet of numbered frames |
| look | `zoom` | one frame, cropped and magnified, with a source-coordinate grid |
| look | `strip` | one region down a frame range, to find exact first/last frames |
| look | `colors` | pixel colours at given points |
| act | `apply` | plan -> censored GIF |
| check | `verify` | crops of the output at every redaction edge, plus a pixel test |

Every command prints JSON, including how to map a point in the image it wrote
back to source pixel coordinates.

## Plan format

```json
{
  "source": "in.gif",
  "output": "out.gif",
  "redactions": [
    {"label": "url bar", "box": [380, 67, 975, 30], "frames": [[0, 291]]},
    {"label": "bookmarks", "box": [24, 101, 1436, 32], "frames": "all", "color": "#1D1D1D"}
  ]
}
```

`box` is `[x, y, w, h]` in source pixels. `frames` is `"all"` or inclusive
`[first, last]` ranges. `color` defaults to `auto`, which samples the ring just
outside the box so the cover takes the colour of the surrounding UI.

## Choices

- **Solid fill, not blur or pixelate.** Blurred text is often still readable and
  sometimes recoverable. A flat box the colour of the chrome around it is
  final, and looks deliberate rather than damaged.
- **Rectangles only.** Screen text sits in rectangles. ffmpeg's `drawbox` does
  this in one pass; an ellipse would need a mask overlay for no gain.
- **Frame numbers, not timestamps.** Seeking a GIF by time is approximate, and a
  single wrong frame leaks the whole secret. Every command addresses frames by
  index, through ffmpeg's `select` filter.
- **One encode.** All boxes go into one filter graph with `palettegen`/
  `paletteuse`, so the GIF is quantised once.
- **`verify` cannot pass on its own.** It proves the box landed where the plan
  said. It cannot know whether the plan was right, so it also writes the crops
  for a human or a model to read.

## Requirements

ffmpeg, ffprobe, ImageMagick 7 (`magick`), Python 3.10+ (standard library only).
