-- Worm fix pass: systematic part repairs. One-time migration of
-- the saved parts; export_all.sh never runs this authoring record.
local H=require('ase_helpers')
local ART=(app.params or {}).art or app.fs.joinPath(H.scriptDir(),'..')
local pal=H.paletteFromJson(app.fs.joinPath(ART,'palette.json'))
local path=app.fs.joinPath(ART,'parts/worm-parts.aseprite')
local s=app.open(path);local parts={};local frames={}
for _,t in ipairs(s.tags) do parts[t.name]=H.flatten(s,t.fromFrame.frameNumber);frames[t.name]=t.fromFrame.frameNumber end
local function set(n,im)
 if not frames[n] then frames[n]=#s.frames+1;s:newEmptyFrame();H.tag(s,n,frames[n],frames[n]) end
 H.setCel(s,s.layers[1],frames[n],im);parts[n]=im
end
local function px(im,x,y,k) H.px(im,x,y,pal,k) end
local function row(im,y,x0,x1,k) H.rect(im,x0,y,x1-x0+1,1,pal,k) end
local shadow={ [25]={18,20},[26]={20,21,31,31},[27]={22,22,30,31},[28]={22,22,29,30},[29]={29,30},[30]={30,30},[36]={23,23,58,58},[37]={23,23,58,58},[38]={23,24,57,58},[39]={23,24,57,57},[40]={23,25,36,38,56,57},[41]={23,27,34,40,55,57},[42]={23,42,54,56},[43]={24,33,41,44,53,55},[44]={26,31,42,54},[45]={44,53},[46]={47,51} }
-- Exact closed-book pixel craft (A1 / B2); keep the registered silhouette.
local closed=parts['book.closed']:clone()
for y=40,43 do px(closed,5,y,'K') end;px(closed,6,45,'K')
row(closed,29,12,16,0);row(closed,30,11,12,0);row(closed,28,18,19,0)
px(closed,4,33,0);px(closed,16,44,'B');px(closed,18,43,'B');px(closed,20,42,'b');px(closed,7,32,'K');px(closed,7,47,0);px(closed,10,26,0);px(closed,10,27,'K')
set('book.closed',closed)
-- The opening page silhouettes use a black outer contour, three spaced text rows,
-- upper-left rim light and an outlined moving page.
local originalOpen=parts['book.open']:clone()
local opened=originalOpen:clone()
for y=37,45 do if opened:getPixel(5,y)~=0 then px(opened,5,y,'K') end end
row(opened,47,18,21,'K')
for y=38,42 do for x=8,27 do if opened:getPixel(x,y)==pal.px.P then px(opened,x,y,'C') end end end
for _,p in ipairs({{38,9,12},{38,14,16},{40,9,11},{40,13,16},{42,9,13}}) do
 for x=p[2],p[3] do px(opened,x,p[1],'P');px(opened,36-x,p[1],'P') end
end
for _,p in ipairs({{12,35},{14,36},{16,37},{21,36},{23,35},{25,35},{27,36}}) do px(opened,p[1],p[2],'C') end
for y=43,46 do for x=5,29 do local v=opened:getPixel(x,y)
 if x<18 and v==pal.px.B then px(opened,x,y,'H') elseif x>=19 and v==pal.px.H then px(opened,x,y,'B') end
end end
set('book.open',opened);set('book.open2',opened:clone())
-- Retain each authored curl, replace its shared base and outline the moving page.
for i=1,5 do
 local old=parts['book.flip'..i];local base=originalOpen;local a=opened:clone()
 -- The moving face is everything differing from the old open pose above r44.
 for y=30,44 do for x=8,29 do local v=old:getPixel(x,y)
  if v~=base:getPixel(x,y) and v~=0 then px(a,x,y,v) end
 end end
 -- A dark page edge is legible over cream without adding any new colour.
 local edges={{{23,34},{27,36},{25,41},{19,44}},{{23,32},{26,34},{23,39},{19,44}},{{18,31},{20,33},{20,39},{19,44}},{{14,32},{16,33},{19,44},{11,40}},{{10,34},{15,36},{19,44},{9,41}}}
 local points=edges[i];for j,p in ipairs(points) do local q=points[j%#points+1];H.line(a,p[1],p[2],q[1],q[2],pal,'P') end
 H.line(a,points[1][1],points[1][2],points[2][1],points[2][2],pal,'K')
 set('book.flip'..i,a)
end
-- Half-raised closed book and opening in-between: compact diagonal silhouettes.
local function polygon(dst,pts,k)
 local lo,hi=48,0;for _,p in ipairs(pts) do lo=math.min(lo,p[2]);hi=math.max(hi,p[2]) end
 for y=lo,hi do local xs={};for j,p in ipairs(pts) do local q=pts[j%#pts+1];if (p[2]<=y and q[2]>y) or (q[2]<=y and p[2]>y) then xs[#xs+1]=p[1]+(y-p[2])*(q[1]-p[1])/(q[2]-p[2]) end end;table.sort(xs)
  for j=1,#xs,2 do row(dst,y,math.ceil(xs[j]),math.floor(xs[j+1]),k) end
 end
 for j,p in ipairs(pts) do local q=pts[j%#pts+1];H.line(dst,p[1],p[2],q[1],q[2],pal,k) end
end
local tilted=H.image(64,48)
polygon(tilted,{{5,36},{17,30},{24,40},{12,47},{5,43}},'K')
polygon(tilted,{{7,37},{17,32},{22,40},{12,45},{7,42}},'B')
H.line(tilted,7,37,17,32,pal,'H');H.line(tilted,12,45,22,40,pal,'b')
H.line(tilted,6,38,6,42,pal,'C');H.line(tilted,7,43,12,46,pal,'P')
set('book.close3',tilted)
local opening=tilted:clone();polygon(opening,{{17,32},{24,34},{25,39},{22,40}},'K');polygon(opening,{{18,33},{23,35},{24,38},{22,39}},'C');set('book.open1',opening)
local asleep=parts['book.rest.sleep']:clone()
for it in asleep:pixels() do local v=it();if v==pal.px.C then it(pal.px.B) end end
for y=39,41 do for x=7,21 do if asleep:getPixel(x,y)==pal.px.B and (asleep:getPixel(x,y-1)==0 or asleep:getPixel(x-1,y)==0) then px(asleep,x,y,'H') end end end
for x=8,20 do if asleep:getPixel(x,42)~=0 then px(asleep,x,42,'C') end end
for x=9,18 do if asleep:getPixel(x,43)~=0 then px(asleep,x,43,'P') end end
row(asleep,47,12,15,'K');for y=42,45 do px(asleep,25,y,'K') end
for y=41,45 do for x=21,24 do if asleep:getPixel(x,y)==pal.px.B then px(asleep,x,y,'b') end end end
set('book.rest.sleep',asleep)
-- Books tuck inside the sprite without canvas clipping: compress height rather
-- than cutting the bottom; outgoing and incoming remain separately visible.
local function standing(top,bottom,left,width)
 local a=H.image(64,48)
 -- Deliberate whole-pixel redraw: a closed rectangle with the diagonal page tip.
 for y=top,bottom do local x0=left+math.max(0,3-(y-top));local x1=left+width-1
  row(a,y,x0,x1,'K');if y>top and y<bottom then row(a,y,x0+1,x1-1,'B');px(a,x0+1,y,'H');px(a,x1-1,y,'b') end
 end
 return a
end
set('book.down1',standing(29,47,5,18));set('book.down2',standing(33,47,5,16));set('book.down3',standing(43,47,5,14))
set('book.peek2',standing(31,33,12,10));set('book.peek3',standing(30,35,12,10))
set('book.up1',standing(34,47,8,15));set('book.up2',standing(30,47,6,17));set('book.up3',closed:clone());set('book.closed.low',standing(30,47,5,18))
-- Shared shadow band, 2-row head/torso and 4-column torso/tail overlap.
for n,a in pairs(parts) do if n:find('^body%.') then
 local v,kind=n:match('^body%.(.+)/(%a+)$')
 local dy=v:find('slump') and 2 or (v=='crouch' and 1 or (v=='stretch1' and -1 or (v=='stretch2' and -2 or 0)))
 if v:find('in2') then dy=dy-1 end
 for it in a:pixels() do if it()==pal.px.g then it(pal.px.G) end end
 for y,cols in pairs(shadow) do local yy=y+(kind=='head' and dy or 0)
  for j=1,#cols,2 do for x=cols[j],cols[j+1] do if yy>=0 and yy<48 and a:getPixel(x,yy)==pal.px.G then px(a,x,yy,'g') end end end
 end
 if kind=='tail' then
  local delta=v=='sit.tail1' and -1 or 0
  for y=31,38 do for x=52,63 do px(a,x,y,0) end end
  for y=32,38 do local yy=y+delta;local left=math.max(48,54-(y-33));row(a,yy,left,59,'G');px(a,left,yy,'K');px(a,59,yy,'K');px(a,58,yy,'g') end
  row(a,32+delta,55,57,'K');row(a,32+delta,58,59,0);px(a,54,32+delta,0)
  row(a,39,48,57,'G');px(a,58,39,'K');px(a,57,39,'g')
 end
 if kind=='torso' then
  for _,p in ipairs({{37,30},{38,30},{39,30}}) do if v:find('in') then px(a,p[1],p[2],'G') end end
  if v=='crouch' then px(a,24,46,'K') end
 end
 set(n,a)
end end
-- Copy seam skin from the saved torso into the last two head rows and extend
-- the torso/tail overlap; no outline is drawn along an internal cut.
for _,v in ipairs({'sit','sit.in1','sit.in2','sit.tail1','slump','slump.in1','slump.in2','crouch','stretch1','stretch2'}) do
 local h,t,a=parts['body.'..v..'/head'],parts['body.'..v..'/torso'],parts['body.'..v..'/tail']
 for y=29,33 do for x=19,32 do if t:getPixel(x,y)~=0 and h:getPixel(x,y)==0 then px(h,x,y,t:getPixel(x,y)) end end end
 for y=36,47 do for x=46,49 do if t:getPixel(x,y)~=0 then px(a,x,y,t:getPixel(x,y)) end end end
 set('body.'..v..'/head',h);set('body.'..v..'/tail',a)
end
-- A10 distinct decaying ring, B8 readable small z, B6 paper with lower lip clear.
local ring=H.image(64,48);H.stamp(ring,{'.q...q.','q.....q','.......','.......','.......','q.....q','.q...q.'},0,0,pal);set('fx.sparkle3',ring)
for _,c in ipairs({'Z','Y','X'}) do set('fx.z.s.'..c,H.stamp(H.image(64,48),{'ZZZ','.Z.','ZZZ'},0,0,pal,{map={Z=c}})) end
set('fx.paper',H.stamp(H.image(64,48),{'CCC','CPC','CCC'},28,28,pal))
set('fx.paper.corner',H.stamp(H.image(64,48),{'C'},30,30,pal))
H.applyPalette(s,pal);H.assertPalette(s,pal);H.save(s,path);s:close()
-- Small systematic parts (A11); preserve lenses' bottom rims on the bob.
path=app.fs.joinPath(ART,'parts/worm-small-parts.aseprite');s=app.open(path);parts={};frames={}
for _,t in ipairs(s.tags) do parts[t.name]=H.flatten(s,t.fromFrame.frameNumber);frames[t.name]=t.fromFrame.frameNumber end
local rest=parts['body.rest'];local bob=H.image(18,18)
for y=1,15 do local src=y<=11 and y-1 or (y==12 and 11 or y);for x=0,17 do px(bob,x,y,rest:getPixel(x,src)) end end
set('body.bob',bob);set('body.droop',bob:clone())
for i=1,2 do local a=H.image(18,18);H.stamp(a,{i==1 and '........KmmmmmK...' or '.........KmmmmK...'},0,i==1 and 11 or 12,pal);set('body.chew'..i,a) end
local half=parts['eyes.half']:clone();row(half,4,2,5,'K');row(half,4,10,14,'K');row(half,5,2,5,'m');row(half,5,10,14,'m');set('eyes.half',half)
for _,v in ipairs({'open','page'}) do local a=H.image(18,18);H.stamp(a,{'BCCbCCB',v=='page' and 'BCPbPCB' or 'BPCbPCB','BCCbCCB','BBBBBBB'},0,12,pal);set('book.'..v,a) end
H.applyPalette(s,pal);H.assertPalette(s,pal);H.save(s,path);s:close();print('systematic saved-part repairs complete')
