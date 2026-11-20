# gifcensor

Cover private regions of a GIF screen recording, and check that the cover holds.

Finding *what* to censor needs a pair of eyes. Applying and checking it does
not. This repo is both halves: `gifcensor.py` is the deterministic one, which
turns a GIF into images a vision model can read precisely, applies a redaction
plan, and checks the result; `SKILL.md` is the prompt that drives it.

## Install

As a skill, for any agent the [skills](https://skills.sh) CLI supports:

    npx skills add miguel-vila/gifcensor

Add `-g` to install it for every project, `-a claude-code` to pick one agent.
Then ask your agent to censor a GIF.

Or use the CLI on its own:

    python3 -I skills/censor-gif/gifcensor.py --help

## Commands

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
    {"label": "bookmarks", "box": [24, 101, 1436, 32], "frames": "all", "color": "#1D1D1D"},
    {"label": "side panel", "box": [1100, 200, 340, 260], "frames": "all", "style": "blur"}
  ]
}
```

`box` is `[x, y, w, h]` in source pixels. `frames` is `"all"` or inclusive
`[first, last]` ranges.

`style` sets how a cover looks, per plan or per redaction:

- `block` (the default) draws a grey panel with an accent border, so a viewer
  sees at once that something was taken out.
- `blend` fills with the colour sampled from the ring just outside the box, so
  the cover disappears into the UI. Use it when the fact of a redaction is
  itself distracting.
- `blur` replaces every square of `window` source pixels with its average, so
  the region keeps its colour and its shape and loses its text. The default
  window is twice the box height, which puts several characters under each
  surviving pixel; `window` sets it yourself. Read the next section before you
  use it on a secret.

`color` overrides the fill in `block` and `blend`. A blur has no colour of its
own.

## Choices

- **A fill is final, a blur is not.** Under a flat box there is nothing left of
  the original. A blur is an average, so part of the original is still in the
  file, and the question is only how much. The averaging here is coarse on
  purpose: with the default window each surviving pixel holds the mean of a
  word, `apply` warns when the window is fine next to the box, and `verify`
  measures what is left at the size of letters. That resists the usual attacks on soft redactions, which rebuild
  text from blocks the size of a character (Depix and Unredacter do this to
  pixelated screenshots) or deconvolve a light blur. Two cases still beat a
  blur, however coarse: a short string an attacker can guess and then confirm
  against the averages, and a target that moves under a fixed box, where every
  frame gives a new set of averages of the same text. Censor with `block` or
  `blend` when the text must not come back, and keep `blur` for the places
  where the shape of the UI is worth more than the last of the secrecy.
- **Rectangles only.** Screen text sits in rectangles. ffmpeg covers one in a
  single pass; an ellipse would need a mask overlay for no gain.
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

    brew install ffmpeg imagemagick

## Layout

    skills/censor-gif/SKILL.md    the prompt that drives the tool
    skills/censor-gif/gifcensor.py
    skills/censor-gif/examples/plan.example.json

## License

MIT.
