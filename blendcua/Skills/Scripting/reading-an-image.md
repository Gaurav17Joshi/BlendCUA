---
name: reading-an-image
description: Getting a number out of a render or a reference photo — crop first, threshold carefully, and what to do when segmentation gives three different answers.
---

# Reading an image

Most visual questions become easy once they are a number. Getting the number is
the part that goes wrong.

## Crop first. It is the cheapest thing you can do

A detail 40 px wide cannot be judged in a 1440 px frame, and this is the single
most common way a wrong build passes its own inspection. Before any cleverness:

```python
from PIL import Image
src = 'mem/<run>/steps/step_001/screenshots/action_05_profile.png'
im = Image.open(src)
w, h = im.size
box = (int(0.43*w), int(0.22*h), int(0.66*w), int(0.70*h))
im.crop(box).resize(((box[2]-box[0])*3, (box[3]-box[1])*3)).save('crop.png')
```

Fractions of the frame, not pixel constants — the same script then survives a
render at a different size. Save it and look at the crop.

## Thresholding, and when it lies

The standard move is: classify each pixel, take the longest run per row or column,
convert to metres with a known scale. It works well on a subject against a plain
background — a duck on white thresholds in one line.

It fails, quietly and confidently, when:

- **the subject is split light/dark.** A pot with a hard key on one side and
  shadow on the other is two very different colours; a brightness test finds half
  of it.
- **the background is the same family as the subject.** Warm stone against a warm
  backdrop; both are "saturated and orange".
- **something overlaps.** Leaves in front of the pot are the same warm hue and get
  counted as pot.

Measured case: three different segmentations of the same reference pot returned
**385, 444 and 499 px** for its width. Nothing errored. Each looked plausible in
isolation. If a measurement matters, get it two ways and see whether they agree —
a single confident number from a thresholder is not evidence.

## When segmentation disagrees with itself, draw a grid

The reliable fallback. Crop the region, scale it up, draw labelled gridlines in
source-image coordinates, and read the edges off the picture:

```python
from PIL import Image, ImageDraw
x0, y0, x1, y1 = 90, 580, 590, 900
c = im.crop((x0, y0, x1, y1)); S = 2
c = c.resize((c.width*S, c.height*S), Image.LANCZOS)
d = ImageDraw.Draw(c)
for X in range(x0, x1, 25):
    px = (X-x0)*S; d.line([(px,0),(px,c.height)], fill=(0,255,255)); d.text((px+2,2), str(X), fill=(0,255,255))
for Y in range(y0, y1, 25):
    py = (Y-y0)*S; d.line([(0,py),(c.width,py)], fill=(255,0,255)); d.text((3,py+2), str(Y), fill=(255,0,255))
c.save('grid.png')
```

Labelling in *original* coordinates is the point — you read "left edge at x≈118,
foot at y≈860" straight off the image and convert with the scale you already have.
This settled a pot measurement that three thresholders could not agree on, and the
answer it gave was confirmed independently afterwards.

## Convert with a stated scale, and never hardcode one

Two things follow from a reference of known size:

```
0.654 image-widths = 0.260 m  ->  1 image-width  = 0.3976 m
                                  1 image-height = 0.6687 m
```

**Two factors, because the image is not square.** Using the wrong axis is a large
silent error. Expose them as two named functions so the mistake cannot be made
quietly.

Never carry a pixel constant between builds. A reviewer's rules once said
`full_width_px = half_width * 2 * 2601`, where 2601 was a different model's
reference height; every pixel figure it quoted on a 2036-wide image was off by
28%. Take the size from the image you are actually looking at.

## Measure the file, not a screenshot of the file

A reference plate measured on screen gave an aspect of 1.71 against the file's own
1.33 — the viewport was cropping it at that zoom. If you want the reference's
dimensions, open the reference. If you want where it sits on screen, project its
own corners rather than eyeballing its edges.

## Measure the right thing

A body scan reported 104 mm on a model built at 79. The scan was correct: the legs
are attached, so a column through them measures back-to-foot. Both false alarms of
that build came from measuring the extent of what was visible rather than the
thing in question. Say in the script's own output *which* columns you sampled and
why.
