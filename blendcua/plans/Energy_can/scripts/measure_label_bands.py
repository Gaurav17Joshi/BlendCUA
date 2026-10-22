from pathlib import Path
import sys, json
import numpy as np
from PIL import Image, ImageDraw
for s in (sys.stdout,sys.stderr):
    try:s.reconfigure(encoding='utf-8',errors='replace')
    except Exception:pass
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'scripts'
a=np.asarray(Image.open(ROOT/'reference.png').convert('RGB')).astype(float)
g=a.mean(2); sat=a.max(2)-a.min(2); h,w=g.shape
# Count neutral bright pixels only in the measured black-label rectangle.  The
# row bands are separated by low counts, not by hand-entered y coordinates.
for thresh in [100,120,140,160,180,200]:
    white=(g>thresh)&(sat<100)
    counts=white[:,267:763].sum(1)
    active=counts>=8
    runs=[]; yy=np.where(active)[0]
    if len(yy):
        s=p=int(yy[0])
        for y in yy[1:]:
            y=int(y)
            if y-p>4:
                runs.append((s,p,int(counts[s:p+1].max()),int(counts[s:p+1].sum())))
                s=y
            p=y
        runs.append((s,p,int(counts[s:p+1].max()),int(counts[s:p+1].sum())))
    print('neutral-bright threshold',thresh,'runs',runs)

# Green components, including the separate ENERGY word but excluding the claws.
green=(a[:,:,1]>a[:,:,0]*1.18)&(a[:,:,1]>a[:,:,2]*1.03)&(a[:,:,1]>65)
for y0,y1,name in [(130,210,'top_green'),(220,1000,'claw_logo'),(1100,1220,'energy')]:
    yy,xx=np.where(green[y0:y1,267:763]);
    if len(xx): print(name,'bbox',(int(xx.min()+267),int(yy.min()+y0),int(xx.max()+267),int(yy.max()+y0)),'area',len(xx))
    else: print(name,'NONE')

# Connected components at a middle threshold, retaining glyph-level bounds. A
# small close joins antialias fragments but does not join separated words.
import cv2
for thresh in [120,160,200]:
    white=((g>thresh)&(sat<100)).astype('uint8')
    white[:80]=0; white[1420:]=0; white[:,:260]=0; white[:,780:]=0
    # remove isolated 1px noise, preserve letters
    num,lab,stats,cent=cv2.connectedComponentsWithStats(white,8)
    comps=[]
    for i in range(1,num):
        x,y,ww,hh,area=map(int,stats[i])
        if area>=4: comps.append((x,y,ww,hh,area))
    comps.sort(key=lambda c:(c[1],c[0]))
    print('components threshold',thresh,'count',len(comps),'first/last',comps[:8],comps[-8:])

# Save crops with source-coordinate grid for the plan evidence.
im=Image.open(ROOT/'reference.png').convert('RGB')
for name,box in [('top_graphics_grid.png',(250,125,780,215)),('logo_graphics_grid.png',(270,245,745,965)),('label_graphics_grid.png',(260,980,775,1380))]:
    c=im.crop(box).resize(((box[2]-box[0])*2,(box[3]-box[1])*2),Image.Resampling.LANCZOS)
    d=ImageDraw.Draw(c); S=2
    for X in range((box[0]//25)*25,box[2]+1,25):
        xx=(X-box[0])*S; d.line((xx,0,xx,c.height),fill=(0,220,255),width=1); d.text((xx+2,2),str(X),fill=(0,220,255))
    for Y in range((box[1]//25)*25,box[3]+1,25):
        yy=(Y-box[1])*S; d.line((0,yy,c.width,yy),fill=(255,0,220),width=1); d.text((2,yy+2),str(Y),fill=(255,0,220))
    c.save(OUT/name)
print('PASS saved graphics grids')
