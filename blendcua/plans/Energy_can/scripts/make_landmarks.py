from pathlib import Path
import json, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont
for s in (sys.stdout,sys.stderr):
    try:s.reconfigure(encoding='utf-8',errors='replace')
    except Exception:pass
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'scripts'
im=Image.open(ROOT/'reference.png').convert('RGB'); a=np.asarray(im).astype(float)
h,w=a.shape[:2]; g=a.mean(2); sat=a.max(2)-a.min(2)
points=[]
def add(name,group,x,y,note):
    x=int(round(x)); y=int(round(y))
    points.append({'name':name,'group':group,'u':round(x/w,6),'v':round(y/h,6),'px':[x,y],'note':note})
# Strict t=12 local-background segmentation gives bbox 267..762, 90..1468.
add('can_top_outer','can',512,90,'topmost row of strict t=12 subject mask; outer silver rim')
add('can_bottom_outer','can',512,1468,'bottommost row of strict t=12 subject mask; lower silver rim')
add('top_rim_left','rim',284,140,'left edge of strict t=12 mask at the broad rim span y=140')
add('top_rim_right','rim',746,140,'right edge of strict t=12 mask at the broad rim span y=140')
add('shoulder_left','silhouette',268,220,'left edge from strict t=12 subject row span at the shoulder-to-body transition')
add('shoulder_right','silhouette',761,220,'right edge from strict t=12 subject row span at the shoulder-to-body transition')
add('body_left_at_y300','silhouette',267,300,'left edge from strict t=12 subject row span in the straight body')
add('body_right_at_y300','silhouette',762,300,'right edge from strict t=12 subject row span in the straight body')
# Upper green claw mask: exact extrema and their median coordinate along the edge.
green=(a[:,:,1]>a[:,:,0]*1.22)&(a[:,:,1]>a[:,:,2]*1.08)&(a[:,:,1]>70)
upper=green.copy(); upper[:220]=False; upper[1000:]=False
ys,xs=np.where(upper)
if len(xs):
    xmin,xmax,ymin,ymax=xs.min(),xs.max(),ys.min(),ys.max()
    add('logo_leftmost','logo',xmin,np.median(ys[xs==xmin]),'leftmost pixel of green upper-logo mask')
    add('logo_rightmost','logo',xmax,np.median(ys[xs==xmax]),'rightmost pixel of green upper-logo mask')
    add('logo_topmost','logo',np.median(xs[ys==ymin]),ymin,'topmost pixel of green upper-logo mask')
    add('logo_bottommost','logo',np.median(xs[ys==ymax]),ymax,'bottommost pixel of green upper-logo mask')
# Thresholded white/neutral bands inside the measured body rectangle.  For each
# named band, choose the first/last active row and median x of that row.
white=(g>120)&(sat<100)
white[:,:267]=False; white[:,763:]=False
for name,y0,y1 in [('monster_word',950,1140),('energy_word',1130,1210),('lower_Chinese',1220,1380)]:
    counts=white[y0:y1+1].sum(1)
    active=np.where(counts>=8)[0]
    if len(active):
        ya=int(y0+active.min()); yb=int(y0+active.max())
        xa=np.median(np.where(white[ya])[0]); xb=np.median(np.where(white[yb])[0])
        add(name+'_top','label',xa,ya,f'first row of threshold gray>120, saturation<100 band for {name}')
        add(name+'_bottom','label',xb,yb,f'last row of threshold gray>120, saturation<100 band for {name}')
# Draw all points; same coordinate set as JSON, with compact group colours.
col={'can':(255,30,30),'rim':(255,80,30),'silhouette':(255,30,30),'logo':(30,80,255),'label':(180,20,180)}
marked=im.copy(); d=ImageDraw.Draw(marked)
try: font=ImageFont.truetype('arial.ttf',16)
except Exception: font=None
for p in points:
    x,y=p['px']; c=col.get(p['group'],(255,0,0))
    d.ellipse((x-5,y-5,x+5,y+5),outline=c,width=3)
    d.line((x-9,y,x+9,y),fill=c,width=1); d.line((x,y-9,x,y+9),fill=c,width=1)
    d.text((x+8,y+2),p['name'],fill=c,font=font)
(ROOT/'marked_Energy_can.json').write_text(json.dumps(points,indent=2),encoding='utf-8')
marked.save(ROOT/'marked_Energy_can.jpg',quality=95)
print('PASS wrote',len(points),'landmarks to marked_Energy_can.json and marked_Energy_can.jpg')
for p in points: print(p['name'],p['px'],'u/v',p['u'],p['v'])
