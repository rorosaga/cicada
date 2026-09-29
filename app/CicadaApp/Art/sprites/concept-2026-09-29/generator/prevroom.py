from PIL import Image
from room import *
from worm import states
from fixture import *
S=states()
shots=[]
m,t=FIRST
shots.append(room('dark','fair',False,S['reading'][0][1],pile_items(m),0,0,{},None))
m,t=MID
shots.append(room('dark','night',True,S['sleeping'][1][1],pile_items(m,'chatgpt-export'),cart_books(t['read']),crate_items(t['aside']),shelf_slots(filed_of(m),FROZEN)[0],1))
m,t=DONE
shots.append(room('light','clear',True,S['happy'][0][1],pile_items(m),0,crate_items(t['aside']),shelf_slots(filed_of(m),FROZEN)[0],None))
px=4
im=Image.new('RGB',(RW*px,len(shots)*(RH*px+8)),(0,0,0))
for i,(g,pl,f) in enumerate(shots):
    th='light' if i==2 else 'dark'
    im.paste(g.png('/tmp/_r.png',px,palette(th)),(0,i*(RH*px+8)))
    print(pl,f)
im.save('prevroom.png')
