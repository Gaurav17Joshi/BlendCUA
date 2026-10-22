from pathlib import Path
import json, sys
import numpy as np
from PIL import Image, ImageDraw

for s in (sys.stdout, sys.stderr):
    try: s.reconfigure(encoding='utf-8', errors='replace')
    except Exception: pass
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'scripts'
im=Image.open(ROOT/'reference.png').convert('RGB'); a=np.asarray(im).astype(float)
h,w=a.shape[:2]; g=a.mean(2); sat=a.max(2)-a.min(2)

def bg_row(y):
    vals=np.concatenate([a[y,0:180], a[y,850:1024]],axis=0)
    return np.median(vals,axis=0)

def bg_gray(y): return float(bg_row(y).mean())

def dark_edges(y, th_margin=32):
    bg=bg_gray(y); th=min(150.0,bg-th_margin)
    row=g[y] < th
    # Require a short dark run so a single antialias/text pixel cannot become the side.
    left=None
    for x in range(190,510):
        if row[x:min(x+8,w)].sum() >= 6:
            left=x; break
    right=None
    for x in range(840,510,-1):
        if row[max(0,x-7):x+1].sum() >= 6:
            right=x; break
    return left,right,bg,th

rows=[140,150,160,170,180,190,200,210,220,230,240,260,280,300,320,350,400,500,600,700,800,900,1000,1100,1200,1300,1350,1380,1400,1410,1420,1430]
print('body edge scans; threshold is gray < min(150, local side median - 32), 8-pixel run')
profile=[]
for y in rows:
    l,r,bg,th=dark_edges(y)
    print(f'y={y:4d} left={l} right={r} width={(r-l+1 if l is not None and r is not None else None)} bg={bg:.2f} th={th:.2f}')
    if l is not None and r is not None:
        profile.append({'y':y,'left':l,'right':r,'width':r-l+1,'width_over_image':(r-l+1)/w,'v':y/h})

# Center-column transitions relative to side background; print all local edges in the two rim windows.
x=w//2
for y0,y1,name in [(75,175,'top'),(1390,1480,'bottom')]:
    print(f'center column rim window {name}:')
    for y in range(y0,y1+1):
        b=bg_gray(y); val=g[y,x]; diff=val-b
        # Print only every local transition above 8 or selected endpoints.
        if abs(diff)>8 or y in (y0,y1):
            print(f'  y={y:4d} gray={val:7.2f} bg={b:7.2f} diff={diff:7.2f} rgb={a[y,x].astype(int).tolist()}')

# Bright bands restricted to the dark-body silhouette interval, so studio background
# cannot be counted as label ink.
bright=((g>150)&(sat<120)) | ((a[:,:,1]>a[:,:,0]*1.18)&(a[:,:,1]>a[:,:,2]*1.03)&(a[:,:,1]>70))
counts=np.zeros(h,dtype=int)
for y in range(h):
    l,r,_,_=dark_edges(y)
    if l is not None and r is not None and r>l:
        counts[y]=int(bright[y,l:r+1].sum())
active=counts>=3
runs=[]
ys=np.where(active)[0]
if len(ys):
    s=p=int(ys[0])
    for y in ys[1:]:
        y=int(y)
        if y-p>5:
            runs.append((s,p,int(counts[s:p+1].max()),int(counts[s:p+1].sum())))
            s=y
        p=y
    runs.append((s,p,int(counts[s:p+1].max()),int(counts[s:p+1].sum())))
print('inside-body bright/green bands:',runs)

# Green logo components and band widths per selected row.
green=(a[:,:,1]>a[:,:,0]*1.22)&(a[:,:,1]>a[:,:,2]*1.08)&(a[:,:,1]>70)
ys,xs=np.where(green & (np.indices((h,w))[0]>220) & (np.indices((h,w))[0]<1000))
if len(xs):
    print('green logo bbox', (int(xs.min()),int(ys.min()),int(xs.max()),int(ys.max())), 'area',len(xs))
    for y in [269,280,300,320,350,400,500,600,700,800,900,939]:
        xx=np.where(green[y])[0]
        print(' green y=%4d x=%s'% (y, (f'{xx.min()}..{xx.max()} ({len(xx)})' if len(xx) else 'none')))

# Rib / vertical flute evidence at a clean row above the logo. Smooth only along x,
# then find broad bright ridges separated by >=25 px.
for y in [225,230,235,240,250]:
    line=g[y,270:761]
    sm=np.convolve(line,np.ones(9)/9,mode='same')
    candidates=[]
    for i in range(12,len(sm)-12):
        if sm[i]>=sm[i-1] and sm[i]>sm[i+1]:
            # broad local peak with prominence versus neighbours 12 px away
            if sm[i]-min(sm[i-10],sm[i+10])>3:
                x0=i+270
                if not candidates or x0-candidates[-1][0]>=18:
                    candidates.append((x0,round(float(sm[i]),1)))
                elif sm[i]>candidates[-1][1]:
                    candidates[-1]=(x0,round(float(sm[i]),1))
    print('rib peaks y',y,':',candidates,'count',len(candidates))

# Save focused evidence crops with a 25px grid, labels in source coordinates.
for name,box in [('top_grid.png',(240,70,790,270)),('label_grid.png',(240,950,790,1410))]:
    c=im.crop(box).resize(((box[2]-box[0])*2,(box[3]-box[1])*2),Image.Resampling.LANCZOS)
    d=ImageDraw.Draw(c)
    S=2
    for X in range(box[0]-(box[0]%25),box[2]+1,25):
        xx=(X-box[0])*S; d.line((xx,0,xx,c.height),fill=(0,220,255),width=1); d.text((xx+2,2),str(X),fill=(0,220,255))
    for Y in range(box[1]-(box[1]%25),box[3]+1,25):
        yy=(Y-box[1])*S; d.line((0,yy,c.width,yy),fill=(255,0,220),width=1); d.text((2,yy+2),str(Y),fill=(255,0,220))
    c.save(OUT/name)

# Save definitive body scans to JSON; percentages are useful for plan targets.
obj={'image_size_px':[w,h], 'body_edge_scans':profile, 'bright_bands_inside_body':runs}
(OUT/'can_target_measurements.json').write_text(json.dumps(obj,indent=2),encoding='utf-8')
print('PASS saved can_target_measurements.json, top_grid.png, label_grid.png')
