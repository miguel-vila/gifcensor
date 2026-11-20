---
name: censor-gif
description: Cover private information in a GIF screen recording (URLs, account ids, emails, tokens, names) with a solid box or a heavy blur. Use when the user asks to censor, redact, blur, anonymise or sanitise a .gif, Kapture or screen capture before sharing it.
---

# Censor a GIF

Drive `gifcensor.py` through four phases. It gives you eyes (`sheet`, `zoom`,
`strip`, `colors`), one hand (`apply`) and a check (`verify`). You supply the
judgement about what counts as private.

## 0. Set up

`gifcensor.py` sits next to this file, in the skill's own directory. Your
harness names that directory when it loads a skill; Claude Code prints
"Base directory for this skill: …". If you were not told it:

```
find ~ -name gifcensor.py -path '*censor-gif*' 2>/dev/null | head -1
```

Make a working directory outside the user's project (a scratch or temp
directory), and put a wrapper there, so no later command depends on how your
shell splits a variable:

```
printf '#!/bin/sh\nexec python3 -I "<skill dir>/gifcensor.py" "$@"\n' > gc
chmod +x gc
```

Every example below calls `./gc`. The tool needs `ffmpeg`, `ffprobe`,
`magick` (ImageMagick 7) and Python 3.10+. Check first, and if one is missing,
tell the user the install line for their platform (`brew install ffmpeg
imagemagick`) rather than working around it:

```
command -v ffmpeg ffprobe magick
```

Never write to the source GIF. Default the output to a new file beside it,
`<name> (censored).gif`.

## 1. Survey

```
./gc probe in.gif
./gc sheet in.gif -o sheet.png --count 21 --cols 3
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
./gc zoom in.gif -o z.png --frame 97 --box 560,40,900,140
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
./gc strip in.gif -o s.png --box 586,178,380,40 --frames 40:190
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
                                 "color": "#141414"},
    {"label": "chat panel",      "box": [1100, 200, 340, 260], "frames": "all",
                                 "style": "blur"}
  ]
}
```

- `box` is `[x, y, w, h]` in source pixels.
- `frames` is `"all"` or a list of inclusive `[first, last]` ranges.
- `style` defaults to `block`: a grey panel with an accent border, so a viewer
  can see that something was removed. Set it on the plan or on one redaction.
  Ask yourself which one the user wants; when they say the covers are too easy
  to miss, they want `block`.
- `color` overrides the fill in `block` and `blend`.

### Which style

| | what it does | what it leaves |
|---|---|---|
| `block` | grey panel, accent border | nothing |
| `blend` | panel in the colour of the UI around the box | nothing |
| `blur` | averages each `window`-sized square of the box | the colours and the shape of what was there |

Use `blur` when the user asks for it, or when the user wants to keep the look
of a busy region that holds nothing short and guessable: a chat panel, a
document body, a list of names. Say in your report that you used it.

Use `block` or `blend` for anything that must not come back: tokens, account
ids, emails, URLs, a single name. A blur is an average, so the text is still in
the file in part. The default window (twice the box height) puts several
characters under each surviving pixel, which stops a reader and stops the
tools that rebuild text from character-sized blocks. It does not stop a guess:
a short string from a format an attacker knows can be rendered and matched
against the averages. If the user asks for a blur over such a thing, cover it
and tell them a flat box is the one that cannot be undone.

Two rules when you do blur:
- `window` is the side, in source pixels, of the square each surviving pixel
  averages. The default suits a box that is one line of text. For a box with
  several lines in it, set `window` to at least three times the height of the
  text, which you read off `zoom`.
- Never leave a moving target under a fixed blur box. Each frame gives a new
  average of the same text, and enough frames give it back. Split it into one
  redaction per stretch where the text is still, as above, or use `block`.

```
./gc apply plan.json          # --dry-run prints the ffmpeg filter graph
```

One pass, one re-encode, palette regenerated per frame, so quality holds.

## 4. Verify, then verify with your eyes

```
./gc verify plan.json --outdir vcheck
./gc sheet out.gif -o out_sheet.png --count 21
```

`verify` reports `machine_pass` per redaction: the box differs from the source,
and it is one flat colour (`block`, `blend`) or holds no detail at the size of
letters (`blur`). That only catches coordinate mistakes and a blur that is far
too light. It cannot tell you a blur is safe.

Then look. Open every image in `vcheck/`. Rows are labelled `before`, `in`,
`after`:
- `in` rows must show no trace of the target, including the top and bottom pixel
  rows of glyphs. Under a blur, read the row as an attacker would: a word you
  can still make out the shape of, or a line of digits whose spacing you can
  count, means the window is too fine.
- `before` and `after` rows must not show the secret either. If they do, the
  range starts too late or ends too early.

Open `out_sheet.png` and re-read the whole recording for anything the plan
missed. Fix the plan and re-run `apply`; it is idempotent on the source.

Report to the user what you covered, what you deliberately left (and why), and
the output path.
