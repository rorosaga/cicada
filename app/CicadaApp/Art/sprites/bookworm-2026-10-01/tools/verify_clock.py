"""Dial/hand geometry and all-pose placement; a clock angle is not an animation loop."""
import math
from night_palette import palette_data, rgba
from verify import check

def verify_clock(report,clock,plan,mask,lamp):
    from verify_room import tag_images, points, scene_points, load
    from verify_night import luma, STATES, NIGHT
    d,images=clock;data=palette_data();colors=data['clock']['colors']
    layer=next(l for l in plan['layers'] if l['prop']=='clock')
    check(layer==dict(prop='clock',sheet='room-clock',x=94,y=34,w=15,h=15,z=1),'clock registration')
    face=tag_images(d,images,'face')[0];dark=tag_images(d,images,'face-night')[0]
    area={(x,y) for x in range(layer['x'],layer['x']+15) for y in range(layer['y'],layer['y']+15)}
    check(not area&(mask|lamp),'clock clear of every pose, window and lamp')
    for name in [f'bookworm-{s}' for s in STATES]+NIGHT:
        for im in load(name)[1]:check(not area&scene_points(im,36,9),'clock clear of '+name)
    check(face.getchannel('A').tobytes()==dark.getchannel('A').tobytes(),'clock day/night face mask')
    check(points(face)=={(x,y) for x in range(15) for y in range(15) if (x-7)**2+(y-7)**2<=49},'round dial silhouette')
    check(sum(luma(p) for p in dark.get_flattened_data())<sum(luma(p) for p in face.get_flattened_data())*.4,'clock dark dial')
    for kind,length in [('hour',3),('minute',5),('second',6)]:
        for night in (False,True):
            suffix='-night' if night else '';tag=kind+suffix
            ink=rgba(colors[tag] if kind=='second' else data['night']['ramps']['K'][0] if night else next(c['hex'] for c in data['colors'] if c['key']=='K'))
            for i,im in enumerate(tag_images(d,images,tag)):
                pp=points(im);angle=i*math.pi/30
                endpoint=(7+math.floor(math.sin(angle)*length+.5),7+math.floor(-math.cos(angle)*length+.5))
                check((7,7) in pp and endpoint in pp and len(pp)<=length+1,tag+': pivot/angle/one-pixel width')
                check({im.getpixel(p) for p in pp}=={ink},tag+': only the declared hand colour')
                check(all(abs((x-7)*math.cos(angle)+(y-7)*math.sin(angle))<=.8 for x,y in pp),tag+': clean line')
                reached={(7,7)}
                while True:
                    more={p for p in pp if any(max(abs(p[0]-q[0]),abs(p[1]-q[1]))<=1 for q in reached)}-reached
                    if not more:break
                    reached|=more
                check(reached==pp,tag+': connected hand')
    report['clock']={'handAnglesVerified':360,'dialFramesVerified':2,'allWormSheetsClear':len(STATES)+len(NIGHT),'bounds':layer,'darkDialLuminanceRatio':sum(luma(p) for p in dark.get_flattened_data())/sum(luma(p) for p in face.get_flattened_data())}
