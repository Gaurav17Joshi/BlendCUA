from pathlib import Path
import json
import sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]
IMG_PATH = ROOT / 'reference.png'
OUT = ROOT / 'scripts'
OUT.mkdir(parents=True, exist_ok=True)

im = Image.open(IMG_PATH).convert('RGB')
a = np.asarray(im).astype(np.float32)
h, w = a.shape[:2]
gray = a.mean(axis=2)
mx = a.max(axis=2)
mn = a.min(axis=2)
sat = mx - mn

# The can is dark against a light, low-saturation studio background.  Use the
# largest dark connected region in the central crop for the black body, and
# keep all row scans explicitly limited to the central subject area.
central = np.zeros((h, w), dtype=bool)
central[:, 150:875] = True
dark = (gray < 145) & central
try:
    import cv2
    n, labels, stats, cents = cv2.connectedComponentsWithStats(dark.astype(np.uint8), 8)
    candidates = [(int(stats[i, cv2.CC_STAT_AREA]), i) for i in range(1, n)
                  if stats[i, cv2.CC_STAT_AREA] > 1000]
    candidates.sort(reverse=True)
    body_label = candidates[0][1]
    body_mask = labels == body_label
    print('cv2 connected dark components:', [(area, tuple(stats[i, :4])) for area, i in candidates[:5]])
except Exception as exc:
    print('cv2 unavailable:', type(exc).__name__, str(exc))
    body_mask = dark

# A local row scan: starting from a proposed center, find the nearest pixel
# whose darkness is clearly below the side-background estimate.
def side_background(y, half=120):
    y0 = max(0, y-half); y1 = min(h, y+half+1)
    # side strips avoid the can and use the average of far-left/far-right patches
    vals = np.concatenate([gray[y0:y1, 0:140].ravel(), gray[y0:y1, 884:1024].ravel()])
    return float(np.median(vals))

def row_edges(y, threshold=145):
    y = int(y)
    bg = side_background(y)
    # darkness relative to local side background is robust to the vertical grey gradient
    score = gray[y] < min(threshold, bg - 25)
    # Resolve each side independently.  A logo or reflection can split the
    # interior into several runs; choosing the central run would then erase the
    # actual silhouette.  Requiring a short dark run suppresses isolated ink.
    left = None
    for x in range(180, w//2):
        if score[x:min(x+8, w)].sum() >= 6:
            left = x
            break
    right = None
    for x in range(w-1, w//2, -1):
        if score[max(0, x-7):x+1].sum() >= 6:
            right = x
            break
    if left is None or right is None or right <= left:
        return None
    return left, right, bg

# Main black body profile. Rows are selected before scanning; all edges are
# found by the same thresholded line procedure, not by visual pixel reads.
scan_rows = [160, 180, 200, 220, 240, 270, 300, 350, 450, 600, 800, 950,
             1050, 1150, 1250, 1350, 1380, 1400, 1420]
profile = []
for y in scan_rows:
    r = row_edges(y)
    if r:
        x0, x1, bg = r
        profile.append({'y': y, 'left': x0, 'right': x1, 'width': x1-x0+1,
                        'bg_median': round(bg, 2)})
print('dark body row profile (gray threshold + local side background):')
for p in profile:
    print('  y={y:4d} x={left:3d}..{right:3d} width={width:3d} bg={bg_median:.1f}'.format(**p))

# Green Monster claw pixels.  The threshold is deliberately expressed in
# channel relationships so it is not tied to a guessed absolute brightness.
green = (a[:,:,1] > a[:,:,0] * 1.22) & (a[:,:,1] > a[:,:,2] * 1.08) & (a[:,:,1] > 70)
# Exclude any tiny background noise and aggregate only the upper graphic.
upper_green = green.copy()
upper_green[0:230] = False
upper_green[1000:] = False
ys, xs = np.where(upper_green)
logo_bbox = None
if len(xs):
    logo_bbox = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
    print('upper green logo bbox:', logo_bbox, 'size=', (logo_bbox[2]-logo_bbox[0]+1, logo_bbox[3]-logo_bbox[1]+1),
          'normalized=', tuple(round(v, 5) for v in (logo_bbox[0]/w, logo_bbox[1]/h, logo_bbox[2]/w, logo_bbox[3]/h)))
else:
    print('upper green logo bbox: NONE')

# Bright/low-saturation graphic band scan in the can area. A row is active if
# it contains enough bright pixels inside the independently resolved silhouette;
# side background and logo holes cannot turn it into a false body width.
bright = (gray > 160) & (sat < 100)
row_counts = np.zeros(h, dtype=int)
for y in range(h):
    rr = row_edges(y)
    if rr:
        l, r, _ = rr
        l = min(l + 5, r)
        r = max(r - 5, l)
        row_counts[y] = int(bright[y, l:r+1].sum())
active = row_counts >= 8
runs = []
ys_active = np.where(active)[0]
if len(ys_active):
    s = p = int(ys_active[0])
    for y in ys_active[1:]:
        y = int(y)
        if y-p > 4:
            runs.append((s, p, int(row_counts[s:p+1].max())))
            s = y
        p = y
    runs.append((s, p, int(row_counts[s:p+1].max())))
print('inside-body bright graphic bands (gray>160, sat<100, row count >=8):', runs)

# Silver rim/foot candidates from neutral high-value pixels, limited to the two
# rim windows.  These are row-band diagnostics, not a substitute for the outer
# contour measurement in segment_can_bounds.py.
metal = (gray > 135) & (sat < 55)
metal_counts = np.zeros(h, dtype=int)
for y in list(range(80, 171)) + list(range(1395, 1481)):
    metal_counts[y] = int(metal[y, 260:770].sum())
metal_active = metal_counts >= 20
mruns = []
my = np.where(metal_active)[0]
if len(my):
    s = p = int(my[0])
    for y in my[1:]:
        y = int(y)
        if y-p > 5:
            mruns.append((s, p, int(metal_counts[s:p+1].max())))
            s = y
        p = y
    mruns.append((s, p, int(metal_counts[s:p+1].max())))
print('neutral-metal rim bands (>=20 pixels in rim windows):', mruns)

# Vertical rib evidence: at a clean black row, list local bright/dark extrema in
# the central interval.  This is a diagnostic count, not a texture coordinate.
rib_y = 235
line = gray[rib_y, 280:745]
# smooth 5 px moving average and find peaks separated by 20 px
kernel = np.ones(5)/5
smooth = np.convolve(line, kernel, mode='same')
peaks=[]
for i in range(8, len(smooth)-8):
    if smooth[i] >= smooth[i-1] and smooth[i] > smooth[i+1] and smooth[i] > np.percentile(smooth, 70):
        x=i+280
        if not peaks or x-peaks[-1] >= 20:
            peaks.append(x)
print('rib highlight candidates at y=%d:'%rib_y, peaks, 'count=', len(peaks))

# Save structured measurements for later plan writing.
measurements = {
    'image': {'width': w, 'height': h},
    'dark_body_profile': profile,
    'logo_green_bbox_px': logo_bbox,
    'logo_green_bbox_norm': ([logo_bbox[0]/w, logo_bbox[1]/h, logo_bbox[2]/w, logo_bbox[3]/h] if logo_bbox else None),
    'bright_graphic_bands_px': runs,
    'neutral_metal_bands_px': mruns,
    'rib_highlight_candidates_x_at_y235': peaks,
    'notes': 'Body rows use gray < min(145, local side median - 25), nearest central contiguous run; green logo uses channel-ratio threshold.'
}
(OUT/'reference_measurements.json').write_text(json.dumps(measurements, indent=2), encoding='utf-8')

# Make diagnostic crops at a scale where label geometry can be inspected.
def save_crop(name, box, scale=2):
    c = im.crop(box)
    c = c.resize((c.width*scale, c.height*scale), Image.Resampling.LANCZOS)
    c.save(OUT/name)

save_crop('can_full_crop.png', (220, 70, 810, 1480), 1)
save_crop('can_top_crop.png', (220, 70, 810, 330), 3)
save_crop('monster_logo_crop_raw.png', (260, 240, 750, 970), 2)
save_crop('can_label_crop.png', (240, 970, 790, 1400), 2)

# Draw only named evidence points onto a copy.  These points are all derived
# from the scans above or from extrema of the green mask/graphic rows.
points=[]
def add_point(name, group, x, y, note):
    x=int(round(x)); y=int(round(y))
    points.append({'name':name, 'group':group, 'u':round(x/w,6), 'v':round(y/h,6),
                   'px':[x,y], 'note':note})

# Outer vertical extents: locate strongest center-column transition in search windows.
def center_transition(y0, y1, direction='up'):
    col = gray[:, w//2]
    grad = np.abs(np.diff(col))
    rng = np.arange(max(0,y0), min(h-1,y1))
    if direction == 'up':
        # no special direction; strongest edge in supplied window
        pass
    yy = int(rng[np.argmax(grad[rng])])
    return yy

top_y = center_transition(75, 125)
bot_y = center_transition(1430, 1480)
add_point('top_rim_outer', 'can', w/2, top_y, 'strongest center-column luminance transition in y=75..125; top of silver rim')
add_point('bottom_rim_outer', 'can', w/2, bot_y, 'strongest center-column luminance transition in y=1430..1480; underside of silver foot rim')

# Use rows whose edges were mechanically resolved.
for p in profile:
    if p['y'] == 300:
        add_point('body_left_at_y300', 'silhouette', p['left'], p['y'], 'left edge from local-background dark run at y=300')
        add_point('body_right_at_y300', 'silhouette', p['right'], p['y'], 'right edge from local-background dark run at y=300')
        break
if logo_bbox:
    add_point('logo_top', 'logo', (logo_bbox[0]+logo_bbox[2])/2, logo_bbox[1], 'top of upper-green pixel mask; crop candidate extent')
    add_point('logo_bottom', 'logo', (logo_bbox[0]+logo_bbox[2])/2, logo_bbox[3], 'bottom of upper-green pixel mask; crop candidate extent')
# Bright text bands: choose the useful runs by their vertical position.
for s,e,mxcount in runs:
    if 950 < s < 1150:
        add_point('monster_word_band_top', 'label', w/2, s, 'top row of bright low-saturation band near MONSTER word')
        add_point('monster_word_band_bottom', 'label', w/2, e, 'bottom row of bright low-saturation band near MONSTER word')
    if 1120 < s < 1230:
        add_point('energy_band_top', 'label', w/2, s, 'top row of bright/green ENERGY band')
        add_point('energy_band_bottom', 'label', w/2, e, 'bottom row of bright/green ENERGY band')

landmark_json = OUT.parent/'marked_Energy_can.json'
if not landmark_json.exists():
    landmark_json.write_text(json.dumps(points, indent=2), encoding='utf-8')
marked = im.copy()
d = ImageDraw.Draw(marked)
try:
    font = ImageFont.truetype('arial.ttf', 18)
except Exception:
    font = None
for item in points:
    x,y=item['px']
    d.ellipse((x-5,y-5,x+5,y+5), outline=(255,30,30), width=3)
    d.line((x-10,y,x+10,y), fill=(255,30,30), width=1)
    d.line((x,y-10,x,y+10), fill=(255,30,30), width=1)
    d.text((x+8,y+3), item['name'], fill=(255,30,30), font=font)
landmark_jpg = OUT.parent/'marked_Energy_can.jpg'
if not landmark_jpg.exists():
    marked.save(landmark_jpg, quality=95)

# The upper logo crop is also a usable artwork source: retain green plus near
# white outline pixels and make all other pixels transparent.  This deliberately
# keeps the white edge but removes the black cylindrical background.
if logo_bbox:
    pad=8
    x0=max(0,logo_bbox[0]-pad); y0=max(0,logo_bbox[1]-pad)
    x1=min(w,logo_bbox[2]+pad+1); y1=min(h,logo_bbox[3]+pad+1)
    crop = a[y0:y1,x0:x1]
    cg=crop.mean(axis=2); cs=crop.max(axis=2)-crop.min(axis=2)
    keep_green=(crop[:,:,1] > crop[:,:,0]*1.15) & (crop[:,:,1] > crop[:,:,2]*1.04) & (crop[:,:,1]>55)
    keep_white=(cg>145) & (cs<115)
    # A small dilation keeps the anti-aliased white border around green islands.
    keep=keep_green | keep_white
    rgba=np.zeros((crop.shape[0],crop.shape[1],4),dtype=np.uint8)
    rgba[:,:,:3]=np.clip(crop,0,255).astype(np.uint8)
    rgba[:,:,3]=np.where(keep,255,0).astype(np.uint8)
    Image.fromarray(rgba,'RGBA').save(OUT/'monster_logo_cutout.png')
    print('saved transparent logo crop:', (x0,y0,x1-1,y1-1), 'alpha_pixels=', int((rgba[:,:,3]>0).sum()))

print('PASS analyzed reference', w, 'x', h, 'landmarks=', len(points), 'outputs=', sorted(p.name for p in OUT.iterdir() if p.is_file()))
