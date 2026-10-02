import sys
from PIL import Image
from worm import *
fr=[f for l in states().values() for _,f in l]+[f for l in responses().values() for _,f in l]
px=7; pad=6; cols=9
bgs=[(28,28,31),(41,34,61),(237,232,244)]
rows=(len(fr)+cols-1)//cols
im=Image.new('RGB',(cols*(32*px+pad),rows*len(bgs)*(32*px+pad)),(0,0,0))
for bi,bg in enumerate(bgs):
  for i,g in enumerate(fr):
    t=g.png('/tmp/_f.png',px,PAL,bg)
    im.paste(t,((i%cols)*(32*px+pad),(bi*rows+i//cols)*(32*px+pad)))
im.save('prev.png')
M=mini_set()
im=Image.new('RGB',(len(M)*(18*10+6),2*18*10+6),(0,0,0))
for i,(n,g) in enumerate(M):
  im.paste(g.png('/tmp/_f.png',10,PAL,(28,28,31)),(i*(18*10+6),0))
  im.paste(g.png('/tmp/_f.png',10,PAL,(236,236,240)),(i*(18*10+6),18*10+6))
im.save('prev_mini.png')
