local H=require('ase_helpers');local S=require('worm_scripts')
local ART=(app.params or {}).art or app.fs.joinPath(H.scriptDir(),'..')
local pal=H.paletteFromJson(app.fs.joinPath(ART,'palette.json'))
local partPath=app.fs.joinPath(ART,'parts/worm-parts.aseprite')
local cyclic={B='1',b='2',H='3',['1']='4',['2']='5',['3']='6',['4']='B',['5']='b',['6']='H'}
local registry=app.fs.isFile(app.fs.joinPath(ART,'qa/registry.json')) and H.readJson(app.fs.joinPath(ART,'qa/registry.json')) or {sheets={}}
local layers={'ref','book-back','body','book','face','brows','mouth','fx'}
-- Populate the documented helper cache in one read, including in the GUI.
local source=app.open(partPath);assert(source,'missing room parts')
for _,t in ipairs(source.tags) do H._parts[partPath..'#'..t.name]=H.flatten(source,t.fromFrame.frameNumber) end
source:close()
-- Anatomical skin outline only: D/L-adjacent black glass rings are structural.
local function skinOutline(im)
  local src=im:clone()
  local function at(x,y) if x<0 or y<0 or x>=64 or y>=48 then return 0 end;return src:getPixel(x,y) end
  for it in src:pixels() do local v=it();local x,y=it.x,it.y
    if v==pal.px.K then
      local outside,glass=false,false
      for yy=y-1,y+1 do for xx=x-1,x+1 do local q=at(xx,yy);if q==0 then outside=true end;if q==pal.px.D or q==pal.px.L then glass=true end end end
      if not outside and not glass then H.px(im,x,y,pal,'G') end
    elseif v==pal.px.G or v==pal.px.g then
      if at(x-1,y)==0 or at(x+1,y)==0 or at(x,y-1)==0 or at(x,y+1)==0 then H.px(im,x,y,pal,'K') end
    end
  end
  return im
end
local function part(n)
 -- Broaden the actual underside's contact patch, not isolated pixels at c60.
 if n=='body.land/base' then local a=H.image(64,48);H.rect(a,45,47,9,1,pal,'K');return a end
 if n:find('fx.bulge.') then
  local a=H.image(64,48);local y=n:find('high') and 30 or (n:find('mid') and 31 or 32)
  H.rect(a,30,y,2,2,pal,'g');H.px(a,32,y,pal,'G');H.px(a,33,y,pal,'K');H.px(a,33,y+1,pal,'K');return a
 end
 return H.loadPart(partPath,n)
end
local function compose(frame,cover,mad)
  local cels={};for _,l in ipairs(layers) do cels[l]=H.image(64,48) end
  for _,p in ipairs(frame.parts) do
    local n=mad and p.layer=='brows' and 'brows.mad' or p.tag
    local img=part(n)
    for i=1,(cover or 1)-1+(p.remap or 0) do img=H.recolor(img,pal,cyclic) end
    H.paste(cels[p.layer],img,p.x,p.y)
  end
  cels.body=skinOutline(cels.body)
  return cels
end
local bookPx={};for _,k in ipairs(pal.keys) do if pal.role[k]:find('^book%.') then bookPx[pal.px[k]]=true end end
local function checkFrame(cels,state,tag,key,ms)
  assert(ms>=40 and ms<=4000,'frame duration cap')
  local im=H.image(64,48);for _,l in ipairs(layers) do if l~='ref' then H.paste(im,cels[l],0,0) end end
  local counts={};local books=0
  for it in im:pixels() do counts[it()]=(counts[it()] or 0)+1;if bookPx[it()] then books=books+1 end end
  assert(books>=20,state..'/'..tag..': book mark')
  assert((counts[pal.px.D] or 0)>=30 and (counts[pal.px.L] or 0)>=6,'glasses mark')
  if state=='sleeping' and (tag=='idle' or tag=='talk.center') then
    assert((counts[pal.px.j] or 0)>=4 and not counts[pal.px.W],'closed sleeping eyes')
    if tag=='idle' and key then assert((counts[pal.px.Z] or 0)>=3,'key z') end
  end
  if state=='error' then
    local E=require('error_eyes')
    for _,pattern in ipairs({E.roomLeft,E.roomRight}) do
      local found=false
      for dx=-1,1 do
        local same=true
        for y,row in ipairs(pattern.rows) do for x=1,#row do
          local want=row:sub(x,x)=='K' and pal.px.K or pal.px.G
          if im:getPixel(pattern.x+x-1+dx,pattern.y+y-1)~=want then same=false end
        end end
        found=found or same
      end
      assert(found,'error diagonal X mark')
    end
    assert((counts[pal.px.S] or 0)>=1,'error drop')
  end
end
for _,state in ipairs(S.states) do
  local name='bookworm-'..state;local spr,ls=H.newSprite(64,48,pal,layers);ls.ref.isVisible=false
  local rec=H.recorder(spr);local rows={}
  for cover=1,(state=='reading' and 3 or 1) do for _,tag in ipairs(S.order[state]) do
    local tagName=tag..(cover==1 and '' or '@'..cover);local frames=S.sheets[state][tag]
    rec:start(tagName);local data={name=tagName,frames={}}
    local total=0
    for i,f in ipairs(frames) do local cels=compose(f,cover);checkFrame(cels,state,tag,i==1,f.ms);total=total+f.ms
      local n=rec:frame(f.ms,cels);data.frames[#data.frames+1]={index=n-1,ms=f.ms,parts=f.parts,eyes=f.eyes,note=f.note,cover=cover}
    end
    local cap=(tag=='intro' or tag=='outro') and 1600 or (tag:find('^perk%.') and 400 or ((tag:find('^talk%.') or tag:find('^gulp%.') or tag:find('^shake%.') or tag:find('^cheer%.')) and 800 or 30000))
    assert(total<=cap and (cap~=30000 or total>=400),'tag total cap: '..state..'/'..tag)
    rec:stop();rows[#rows+1]=data
  end end
  rec:apply();H.addSlice(spr,'ink',H.spriteInk(spr));for _,n in ipairs({'eye','lensL','lensR'}) do H.addSlice(spr,n,S.slices[n]) end
  if state=='error' then H.addSlice(spr,'errorLensL',{x=10,y=17,w=5,h=6}) end
  H.assertPalette(spr,pal);H.save(spr,app.fs.joinPath(ART,'src/'..name..'.aseprite'))
  registry.sheets[name]={canvas={w=64,h=48},tags=rows}
  H.exportFramePng(spr,1,app.fs.joinPath(ART,'qa/'..name..'-key@8x.png'),8)
  print(name..': '..#spr.frames..' frames / '..#spr.tags..' tags');spr:close()
end
local demo=H.newSprite(64,48,pal,layers);local rec=H.recorder(demo);rec:start('mad')
for _,f in ipairs(S.sheets.awake.idle) do rec:frame(f.ms,compose(f,1,true)) end
rec:stop();rec:apply();H.exportGif(demo,app.fs.joinPath(ART,'demo/bookworm-mad-demo@6x.gif'),'mad',6);demo:close()
-- The app advances cover tags at each boundary. A standalone per-cover GIF
-- resets its own cover; this review demo joins all three and loops seamlessly.
local cycle=H.newSprite(64,48,pal,layers);local cycleRec=H.recorder(cycle);cycleRec:start('cycle')
for cover=1,3 do for _,f in ipairs(S.sheets.reading.idle) do cycleRec:frame(f.ms,compose(f,cover)) end end
cycleRec:stop();cycleRec:apply()
H.exportGif(cycle,app.fs.joinPath(ART,'demo/bookworm-reading-cycle@6x.gif'),'cycle',6);cycle:close()
H.writeJson(app.fs.joinPath(ART,'qa/registry.json'),registry)
