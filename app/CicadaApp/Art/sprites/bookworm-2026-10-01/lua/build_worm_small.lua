local H=require('ase_helpers')
local ART=(app.params or {}).art or app.fs.joinPath(H.scriptDir(),'..')
local pal=H.paletteFromJson(app.fs.joinPath(ART,'palette.json'))
local path=app.fs.joinPath(ART,'parts/worm-small-parts.aseprite')
local source=app.open(path);assert(source,'missing menu-bar parts')
for _,t in ipairs(source.tags) do H._parts[path..'#'..t.name]=H.flatten(source,t.fromFrame.frameNumber) end
source:close()
local order={'awake','sleeping','digesting','happy','curious','hungry','reading','error'}
local data={
 awake={{1800},{100,{eyes='blink'}},{1400},{300,{body='bob'}},{600}},
 sleeping={{700,{eyes='blink',z='Z',zy=3}},{700,{eyes='blink',z='Z',zy=2}},{700,{eyes='blink',z='Y',zy=1}},{700,{eyes='blink',z='Y',zy=0,chew=2}}},
 digesting={{250,{chew=1}},{250,{chew=2}}},
 happy={{1600},{160,{body='bob'}},{160},{400,{sparkle=true}},{1200}},
 curious={{1200,{brow=2}},{300,{brow=1}},{900,{brow=2}},{400,{eyes='left',tilt=true,brow=2}}},
 hungry={{2000,{eyes='half'}},{400,{eyes='blink'}},{1600,{eyes='half'}},{800,{body='droop',eyes='half'}}},
 reading={{600,{eyes='left',book='open'}},{600,{eyes='right',book='open'}},{150,{eyes='right',book='page'}},{600,{eyes='left',book='open'}}},
 error={{600,{eyes='error',sweat=2}},{100,{eyes='error',sweat=2,dx=-1}},{400,{eyes='error',sweat=2}},{400,{eyes='error',sweat=3}}},
}
local registry=H.readJson(app.fs.joinPath(ART,'qa/registry.json'))
registry.sheets['bookworm-small-dark']=nil -- owner removed this appearance sheet
local function compose(o)
 o=o or {};local c={};for _,n in ipairs({'body','book','face','fx'}) do c[n]=H.image(18,18) end
 local dy=o.body and 1 or 0;local dx=o.dx or 0
 H.paste(c.body,H.loadPart(path,'body.'..(o.body or 'rest')),0,0)
 -- Tremble the neck, keeping the full glasses contour inside the 18px grid.
 if dx~=0 then
  local base=H.loadPart(path,'body.rest');H.rect(c.body,0,11,18,5,pal,0)
  for y=11,15 do for x=0,17 do local px=base:getPixel(x,y);if px~=0 then H.px(c.body,x+dx,y,pal,px) end end end
 end
 H.paste(c.face,H.loadPart(path,'eyes.'..(o.eyes or 'center')),0,dy)
 if o.book then H.paste(c.book,H.loadPart(path,'book.'..o.book),0,0) end
 if o.chew then H.paste(c.body,H.loadPart(path,'body.chew'..o.chew),0,0) end
 if o.z then H.rect(c.fx,16,o.zy,2,2,pal,o.z) end
 if o.sparkle then H.px(c.fx,16,2,pal,'q') end
 if o.sweat then H.rect(c.fx,17,o.sweat,1,2,pal,'S') end
 if o.brow then H.line(c.fx,10,o.brow,12,o.brow,pal,'K') end
 if o.tilt then H.px(c.body,13,13,pal,'m');H.px(c.body,14,13,pal,'K') end
 return c
end
do
 local name='bookworm-small'
 local s,ls=H.newSprite(18,18,pal,{'ref','body','book','face','fx'});ls.ref.isVisible=false
 local rec=H.recorder(s);local tags={}
 for _,n in ipairs(order) do rec:start(n);local tag={name=n,frames={}}
  for _,v in ipairs(data[n]) do local idx=rec:frame(v[1],compose(v[2]));tag.frames[#tag.frames+1]={index=idx-1,ms=v[1],options=v[2] or {}} end
  rec:stop();tags[#tags+1]=tag
 end
 rec:apply();H.addSlice(s,'lensL',{x=2,y=5,w=4,h=4});H.addSlice(s,'lensR',{x=10,y=5,w=5,h=4})
 H.assertPalette(s,pal);H.save(s,app.fs.joinPath(ART,'src/'..name..'.aseprite'))
 H.save(s,app.fs.joinPath(ART,'menubar.aseprite'))
 registry.sheets[name]={canvas={w=18,h=18},tags=tags}
 print(name..': '..#s.frames..' frames / '..#s.tags..' tags');s:close()
end
H.writeJson(app.fs.joinPath(ART,'qa/registry.json'),registry)
