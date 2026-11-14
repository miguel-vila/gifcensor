---
name: censor-gif
description: Cover private information in a GIF screen recording (URLs, account ids, emails, tokens, names). Use when the user asks to censor, redact, blur, anonymise or sanitise a .gif, Kapture or screen capture before sharing it.
---

# Censor a GIF

Drive `gifcensor.py` through four phases. It gives you eyes (`sheet`, `zoom`,
`strip`, `colors`), one hand (`apply`) and a check (`verify`). You supply the
judgement about what counts as private.

```
GC="python3 -I ~/repos/gifcensor/gifcensor.py"
```

Work in the scratchpad. Never overwrite the source GIF.

## 1. Survey

```
$GC probe in.gif
$GC sheet in.gif -o sheet.png --count 21 --cols 3
```

Read `sheet.png`. Frame numbers are burned under each tile. Write down every
region that may carry private information, and roughly which frames it is on.

If the user named what to censor, that list rules. If they were vague, treat as
private: URLs and hostnames, account ids and numbers, emails, usernames and real
names, access keys and tokens, ticket/PR titles and bodies, bookmark bars, tab
titles, avatars, internal service and role names.

## 2. Pin down boxes and frame ranges

Never take a coordinate off the contact sheet. The sheet is scaled down, and a
box that is a few pixels short leaks the top of the text.

```
$GC zoom in.gif -o z.png --frame 97 --box 560,40,900,140
```

The pink grid is labelled in **source** pixels. Read the box straight off it,
then add about 4px of margin on each side: anti-aliased text bleeds past its
glyph box.

When a box has to land between glyphs — covering one word of a string and
leaving the rest readable — measure instead of guessing. Crop the text line,
flatten it to one row, and read off the columns that carry ink:

```
ffmpeg -v error -i in.gif -vf "select='eq(n,310)',crop=180:20:640:306" \
       -fps_mode passthrough row.png
magick row.png -colorspace gray -resize 180x1! txt:-
```

Columns near the background value are gaps between glyphs; the first and last
column of each run gives you an exact edge.

Find the first and last frame a thing is on screen:

```
$GC strip in.gif -o s.png --box 586,178,380,40 --frames 40:190
```

One row per frame with its number on the left, columns read top-to-bottom then
left-to-right. Narrow with `--step 1` once you are close. Widen the final range
by ~2 frames at each end — covering a frame too many costs nothing.

Watch for:
- **The region moves.** Scrolling or a panel that slides means one target needs
  several redactions, one per stretch where it is still.
- **Different pages, same pixel area.** A box that fits the URL bar on page A
  may sit over body text on page B. Check the boundary frames.
- **Things that come back.** A dialog that opens, closes and reopens needs two
  ranges, not one wide one.

## 3. Plan and apply

Write `plan.json`:

```json
{
  "source": "/abs/path/in.gif",
  "output": "/abs/path/out.gif",
  "redactions": [
    {"label": "browser url bar", "box": [380, 67, 975, 30], "frames": [[0, 291]]},
    {"label": "bookmarks bar",   "box": [24, 101, 1436, 32], "frames": "all"},
    {"label": "aws account id",  "box": [628, 278, 256, 16], "frames": [[61, 123], [125, 171]],
                                 "color": "#141414"}
  ]
}
```

- `box` is `[x, y, w, h]` in source pixels.
- `frames` is `"all"` or a list of inclusive `[first, last]` ranges.
- `style` defaults to `block`: a grey panel with an accent border, so a viewer
  can see that something was removed. Set `"style": "blend"` on the plan or on
  one redaction to fill with the colour of the UI around the box instead, which
  hides the fact of the redaction. Ask yourself which the user wants; when they
  say the covers are too easy to miss, they want `block`.
- `color` overrides the fill in either style.

```
$GC apply plan.json          # --dry-run prints the ffmpeg filter graph
```

One pass, one re-encode, palette regenerated per frame, so quality holds.

## 4. Verify, then verify with your eyes

```
$GC verify plan.json --outdir vcheck
$GC sheet out.gif -o out_sheet.png --count 21
```

`verify` reports `machine_pass` per redaction: the inside of the box is one flat
colour and differs from the source. That only catches coordinate mistakes.

Then look. Open every image in `vcheck/`. Rows are labelled `before`, `in`,
`after`:
- `in` rows must show no trace of the target, including the top and bottom pixel
  rows of glyphs.
- `before` and `after` rows must not show the secret either. If they do, the
  range starts too late or ends too early.

Open `out_sheet.png` and re-read the whole recording for anything the plan
missed. Fix the plan and re-run `apply`; it is idempotent on the source.

Report to the user what you covered, what you deliberately left (and why), and
the output path.
