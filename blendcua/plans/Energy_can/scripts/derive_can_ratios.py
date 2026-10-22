from pathlib import Path
import json, sys
for s in (sys.stdout,sys.stderr):
    try:s.reconfigure(encoding='utf-8',errors='replace')
    except Exception:pass
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'scripts'
W,H=1024,1536
x0,x1,y0,y1=267,762,90,1468
full_h=y1-y0+1; body_w=x1-x0+1
print(f'full strict bbox {body_w}x{full_h}px W/H={body_w/full_h:.6f} H/W={full_h/body_w:.6f}')
H_world=4.0
print(f'body radius/H={(body_w/2)/full_h:.6f}; body diameter/H={body_w/full_h:.6f}; at H={H_world:.1f}, diameter={body_w/full_h*H_world:.6f}, radius={(body_w/2)/full_h*H_world:.6f}')
for name,y,width in [('top_rim_at_y140',140,463),('shoulder_y180',180,463),('shoulder_y200',200,478),('shoulder_y220',220,494),('body_y300',300,496),('lower_taper_y1380',1380,493)]:
    print(f'{name}: y={y} v={y/H:.6f} z_from_bottom/H={(y1-y)/full_h:.6f} width={width}px width/body={width/body_w:.6f} width/H={width/full_h:.6f}')
for name,yy in [('top_text_top',145),('top_text_bottom',191),('logo_top',269),('logo_bottom',939),('monster_top',1007),('monster_bottom',1124),('energy_top',1140),('energy_bottom',1183),('lower_text_top',1249),('lower_text_bottom',1365),('silver_bottom_start',1419)]:
    print(f'{name}: y={yy} v={yy/H:.6f} z_from_bottom/H={(y1-yy)/full_h:.6f}')
print(f'logo width/body=423/496={423/body_w:.6f}; logo height/fullH=671/{full_h}={671/full_h:.6f}')
print(f'top rim width/body=463/496={463/body_w:.6f}; top silver span/height=(155-90+1)/{full_h}={66/full_h:.6f}; bottom silver span/height=(1468-1419+1)/{full_h}={50/full_h:.6f}')
print('PASS derived normalized targets')
(OUT/'derived_can_ratios.txt').write_text('Derived from strict t=12 mask bbox x267..762 y90..1468 and scan bands. See stdout above.\n',encoding='utf-8')
