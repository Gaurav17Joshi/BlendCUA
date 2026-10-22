from pathlib import Path
import sys
import numpy as np
from PIL import Image, ImageDraw

for s in (sys.stdout, sys.stderr):
    try: s.reconfigure(encoding='utf-8', errors='replace')
    except Exception: pass
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'scripts'
a=np.asarray(Image.open(ROOT/'reference.png').convert('RGB')).astype(float)
g=a.mean(2); sat=a.max(2)-a.min(2)
h,w=g.shape

def print_profile(x, y0,y1):
    vals=g[y0:y1+1,x]
    grad=np.abs(np.diff(vals))
    inds=np.argsort(grad)[::-1][:20]
    print(f'center/column x={x}, y={y0}..{y1}')
    for i in sorted(inds[:12]):
        y=y0+int(i)
        print(f'  y={y:4d} gray={g[y,x]:7.2f} next={g[y+1,x]:7.2f} absgrad={grad[i]:7.2f} rgb={a[y,x].astype(int).tolist()}')

print_profile(w//2,70,180)
print_profile(w//2,1360,1485)

# At selected rows, find strongest horizontal luminance edges near each guessed side.
# Each side search is deliberately narrow around the can, and prints a local
# neighbourhood so the threshold choice can be checked against pixels.
for y in [95,100,105,110,115,120,125,130,135,140,145,150,155,160,170,180,190,200,210,220,240,300,500,900,1000,1200,1350,1380,1400,1410,1420,1430,1440,1450,1460]:
    dx=np.abs(np.diff(g[y]))
    left_range=np.arange(220,381)
    right_range=np.arange(640,821)
    li=int(left_range[np.argmax(dx[left_range])])
    ri=int(right_range[np.argmax(dx[right_range])])
    print(f'edge y={y:4d}: left_grad@{li}={dx[li]:.1f} left_pair={g[y,li]:.1f}/{g[y,li+1]:.1f} right_grad@{ri}={dx[ri]:.1f} right_pair={g[y,ri]:.1f}/{g[y,ri+1]:.1f}')

# Build a conservative outer silhouette from per-row edge peaks in windows, then
# save it as a diagnostic overlay.  The edge peak for each side is the strongest
# gradient with a dark-inside / light-outside sign, not a text pixel.
edge_pts=[]
for y in range(70,1481):
    dx=np.diff(g[y])
    # left: light -> dark as x increases; right: dark -> light as x increases
    lrs=np.arange(230,390)
    rrs=np.arange(630,810)
    lscore=-dx[lrs]
    rscore=dx[rrs]
    li=int(lrs[np.argmax(lscore)])
    ri=int(rrs[np.argmax(rscore)])
    if lscore.max()>8 and rscore.max()>8:
        edge_pts.append((li,ri,y,float(lscore.max()),float(rscore.max())))
print('edge point count=',len(edge_pts))
# Use robust quantiles of valid edge points only for rough outer box; report all
# candidate extrema and medians in zones to avoid text/rib false peaks.
for y0,y1,name in [(70,180,'top_rim'),(180,230,'shoulder'),(230,1400,'body'),(1400,1481,'bottom_rim')]:
    q=[p for p in edge_pts if y0<=p[2]<=y1]
    if q:
        print(name,'n=',len(q),'left median/min/max=',np.median([p[0] for p in q]),min(p[0] for p in q),max(p[0] for p in q),
              'right median/min/max=',np.median([p[1] for p in q]),min(p[1] for p in q),max(p[1] for p in q))

# Save a compact edge evidence image.
out=Image.open(ROOT/'reference.png').convert('RGB')
d=ImageDraw.Draw(out)
for li,ri,y,ls,rs in edge_pts[::3]:
    d.point((li,y),fill=(255,0,0)); d.point((ri,y),fill=(0,0,255))
out.crop((180,60,850,1490)).save(OUT/'edge_profile_overlay.png')
print('PASS profile diagnostics saved edge_profile_overlay.png')
