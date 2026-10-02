-- Seed once. These files become the editable source of truth; rebuilds never write them.
local H=require('ase_helpers')
local ART=app.params.art or app.fs.joinPath(H.scriptDir(),'..')
local pal=H.paletteFromJson(app.fs.joinPath(ART,'palette.json'))
local function im() return H.image(64,48) end
local function polygon(dst,points,key)
  local lo,hi=99,-99; for _,p in ipairs(points) do lo=math.min(lo,p[2]);hi=math.max(hi,p[2]) end
  for y=lo,hi do
    local xs={}
    for i,p in ipairs(points) do local q=points[i%#points+1]
      if (p[2]<=y and q[2]>y) or (q[2]<=y and p[2]>y) then xs[#xs+1]=p[1]+(y-p[2])*(q[1]-p[1])/(q[2]-p[2]) end
    end
    table.sort(xs)
    for i=1,#xs,2 do H.rect(dst,math.ceil(xs[i]),y,math.floor(xs[i+1])-math.ceil(xs[i])+1,1,pal,key) end
  end
  for i,p in ipairs(points) do local q=points[i%#points+1];H.line(dst,p[1],p[2],q[1],q[2],pal,key) end
end
local function outlined(points,shade)
  local mask=im();polygon(mask,points,'G');local dst=mask:clone()
  for it in mask:pixels() do if it()~=0 then
    local x,y=it.x,it.y;local edge=false
    for _,v in ipairs({{-1,0},{1,0},{0,-1},{0,1}}) do local a,b=x+v[1],y+v[2]
      if a<0 or a>=64 or b<0 or b>=48 or mask:getPixel(a,b)==0 then edge=true end
    end
    if edge then H.px(dst,x,y,pal,'K') elseif shade and y>=shade(x) then H.px(dst,x,y,pal,'g') end
  end end
  return dst
end
local function translated(src,dx,dy) return H.paste(im(),src,dx,dy) end
local parts={};local order={}
local function put(n,img) parts[n]=img;order[#order+1]=n end
-- Independently redrawn from the fitted tracing, with a continuous 1px contour and a smooth S-tail.
local body=outlined({{23,10},{28,10},{31,11},{34,14},{34,27},{31,31},{33,32},{38,30},{41,31},{45,35},{48,36},{51,35},{54,32},{56,34},{59,35},{59,38},{57,42},{54,46},{50,47},{46,47},{42,45},{38,42},{35,41},{32,42},{29,45},{26,46},{23,45},{21,41},{19,36},{19,30},{17,28},{16,23},{17,17},{20,13}},function(x) return x<36 and (35+math.floor((x-21)/4)) or (40+math.floor(math.abs(x-38)/5)) end)
-- Charcoal frames: outer K, broad D body, top-left L light, and an inner K ring.
local function ring(rows,x,y)
  H.stamp(body,rows,x,y,pal)
end
ring({'...KKKKK...','..KLLLLLK..','.KLDDDDDLK.','KLDDKKKDDLK','KDDKGGGKDDK','KDDKGGGKDDK','KDDKGGGKDDK','KDDKGGGKDDK','KDDKGGGKDDK','.KDKGGGKDK.','.KDLKKKDDK.','..KDLLLDK..','...KKKKK...'},8,13)
ring({'....KKKKKK....','..KKLLLLLLKK..','.KLDDDDDDDDLK.','KLDDKKKKKKDDLK','KDDKGGGGGGKDDK','KDDKGGGGGGKDDK','KDDKGGGGGGKDDK','KDDKGGGGGGKDDK','KDDKGGGGGGKDDK','KDDKGGGGGGKDDK','KDDKGGGGGGKDDK','.KDLKKKKKKDDK.','..KDLLLLLLDK..','...KKKKKKKK...'},20,14)
H.stamp(body,{'KLK','DLD','KKK'},18,19,pal)
H.stamp(body,{'KLLKK....','KDDLLKK..','.KKDDDLK.','...KKDDLK','.....KDDK','......KK.'},33,19,pal)
-- Body seams overlap without adding an internal outline.
local head,torso,tail=im(),im(),im()
for it in body:pixels() do if it()~=0 then
  if it.y<=31 then H.px(head,it.x,it.y,pal,it()) end
  if it.y>=29 and it.x<=49 then H.px(torso,it.x,it.y,pal,it()) end
  if it.y>=29 and it.x>=48 then H.px(tail,it.x,it.y,pal,it()) end
end end
local variants={'sit','sit.in1','sit.in2','sit.tail1','slump','slump.in1','slump.in2','crouch','stretch1','stretch2'}
for _,v in ipairs(variants) do
  local h,t,a=head:clone(),torso:clone(),tail:clone()
  if v:find('slump') then h=translated(h,0,2) end
  if v=='crouch' then h=translated(h,0,1);H.px(t,24,46,pal,'g') end
  if v=='stretch1' or v=='stretch2' then h=translated(h,0,v=='stretch1' and -1 or -2) end
  if v:find('in1') or v:find('in2') then
    -- Hump expands upward; bottom stays planted. The head follows in in2.
    for x=35,42 do for y=29,34 do if t:getPixel(x,y)~=0 then H.px(t,x,y-1,pal,t:getPixel(x,y)) end end end
  end
  if v:find('in2') then h=translated(h,0,-1) end
  if v=='sit.tail1' then
    local tmp=im();for it in a:pixels() do local dy=it.x>=54 and it.y<40 and -1 or 0;H.px(tmp,it.x,it.y+dy,pal,it()) end;a=tmp
  end
  put('body.'..v..'/head',h);put('body.'..v..'/torso',t);put('body.'..v..'/tail',a)
end
-- Exact rectangular interiors are the lens slices. All eye stamps replace them, preventing old pupils.
local function eyes(kind,dx,dy)
  local e=im();H.rect(e,12,17,3,6,pal,'G');H.rect(e,24,18,6,7,pal,'G')
  dx,dy=dx or 0,dy or 0
  if kind:find('error') then
    require('error_eyes').room(function(x,y,k) H.px(e,x,y,pal,k) end)
  elseif kind=='closed' then
    H.stamp(e,{'j.j','jjj'},12,20,pal);H.stamp(e,{'j....j','.jjjj.'},24,21,pal)
  elseif kind=='happy' then H.stamp(e,{'K.K','...'},12,19,pal);H.stamp(e,{'.K..K.','K.KK.K'},24,20,pal)
  else
    local p='K'
    H.rect(e,14+math.max(-1,math.min(0,dx)),20+dy,1,2,pal,p)
    H.stamp(e,{'.KK.','KKKK','.KK.'},25+dx,21+dy,pal,{map={K=p}})
    -- Highlights stay above/left of pupils, as in the owner's stepped specular.
    H.stamp(e,{'W.','WW'},12,17,pal);H.stamp(e,{'.W','WW'},24,18,pal)
    if kind=='wide' then H.px(e,26,19,pal,'W') end
    if kind=='half' or kind=='blink.half' then
      H.rect(e,12,17,3,kind=='half' and 2 or 3,pal,'j');H.rect(e,24,18,6,kind=='half' and 2 or 4,pal,'j')
    end
  end
  return e
end
for _,v in ipairs({'center','left','right','up','up.left','up.right','half','blink.half','closed','happy','wide','error','error.left','error.right'}) do
  put('eyes.'..v,eyes(v,v:find('left') and -1 or (v:find('right') and 1 or 0),v:find('up') and -1 or 0))
end
for row=0,2 do for i=0,3 do local suffix=row==0 and '' or (row==1 and 'b' or 'c');put('eyes.down.l'..i..suffix,eyes('center',i-2,row==2 and 1 or 0)) end end
local brows={none={},happy={{10,11,'..KKK..'},{10,12,'.K...K.'},{10,13,'K.....K'},{25,9,'..KKKK.'},{25,10,'.K....K'},{25,11,'K.....K'}},mad={{11,10,'KK'},{12,11,'KDK'},{13,12,'KDK'},{14,13,'KK'},{29,9,'KK'},{28,10,'KDK'},{27,11,'KK'}},sad={{15,10,'KK'},{13,11,'KKK'},{12,12,'KK'},{26,8,'KK'},{27,9,'KKK'},{29,10,'KK'}},tired={{11,12,'KKKKK'},{27,11,'KKKKK'},{31,12,'KK'}},worried={{15,10,'KK'},{14,11,'KK'},{12,12,'KKK'},{26,12,'KKK'}},curious={{10,11,'..KKK..'},{10,12,'.K...K.'},{10,13,'K.....K'},{27,11,'KKKKK'}}}
for _,v in ipairs({'none','happy','sad','tired','worried','mad','curious'}) do
  local b=im();for _,p in ipairs(brows[v]) do H.stamp(b,{p[3]},p[1],p[2],pal) end
  put('brows.'..v,b);put('brows.'..v..'+1',translated(b,0,-1))
end
local mouths={none={},talk1={'KrrK','KKKK'},talk2={'.KKK.','KrrrK','.KKK.'},chew1={'KKK'},chew2={'KrrK','KKKK'},gulpOpen={'.KKK.','KrrrK','KrrrK','.KKK.'},yawn={'..KK..','.KrrK.','KrrrrK','.KrrK.','..KK..'},smile={'K...K','.KKK.'},mumble1={'KK'},mumble2={'KrK'}}
for _,v in ipairs({'none','talk1','talk2','chew1','chew2','gulpOpen','yawn','smile','mumble1','mumble2'}) do local m=im();H.stamp(m,mouths[v],26,29,pal);put('mouth.'..v,m) end
-- Book parts are independent of the body. The closed book keeps the source's diagonal top and stripe rhythm.
local closed=im()
polygon(closed,{{4,31},{10,26},{11,27},{11,29},{22,28},{22,42},{10,47},{7,47}},'K')
polygon(closed,{{5,31},{10,27},{10,29},{7,32}},'C');H.line(closed,8,31,10,29,pal,'P')
polygon(closed,{{8,33},{21,29},{21,41},{10,46}},'B')
H.line(closed,9,33,9,46,pal,'H');H.line(closed,7,33,7,45,pal,'b');H.line(closed,6,33,6,43,pal,'B');H.line(closed,8,33,8,46,pal,'K');H.line(closed,21,30,21,41,pal,'b')
put('book.closed',closed);put('book.closed.low',translated(closed,2,0))
local open=im();polygon(open,{{5,37},{10,35},{18,37},{25,35},{30,37},{28,45},{19,47},{16,46},{7,45}},'b')
polygon(open,{{6,36},{11,34},{18,37},{24,34},{29,36},{27,43},{19,45},{17,44},{8,43}},'K')
polygon(open,{{7,37},{11,35},{17,38},{17,43},{9,42}},'C')
polygon(open,{{19,38},{24,35},{28,37},{26,42},{19,44}},'C')
H.line(open,18,38,18,44,pal,'P');H.line(open,7,44,16,46,pal,'B');H.line(open,20,45,27,43,pal,'H')
for y=38,41,2 do H.line(open,10,y,15,y+1,pal,'P');H.line(open,21,y+1,25,y,pal,'P') end
put('book.open',open)
local flips={{{24,34},{28,36},{26,41},{19,44}},{{24,32},{27,34},{24,39},{19,44}},{{19,31},{21,33},{21,39},{19,44}},{{15,32},{17,33},{19,44},{12,40}},{{11,34},{16,36},{19,44},{10,41}}}
for i,p in ipairs(flips) do local f=open:clone();polygon(f,p,'P');local pp={};for _,v in ipairs(p) do pp[#pp+1]={v[1]-1,v[2]} end;polygon(f,pp,'C');H.line(f,p[1][1]-1,p[1][2],18,43,pal,'P');put('book.flip'..i,f) end
for i=1,3 do
  local b= i==3 and closed:clone() or open:clone()
  if i<3 then polygon(b,{{8,35},{15,34-i},{22,34},{24,42},{18,45},{9,43}},'B');H.line(b,9,35,9,42,pal,'H') end
  put('book.close'..i,b)
  -- Tuck behind torso, not below the canvas. Retain pages at left for continuity and the book mark.
  put('book.down'..i,translated(closed,4+i*2,0))
  put('book.up'..i,translated(closed,10-i*3,0))
end
put('book.open1',parts['book.close2']:clone());put('book.open2',parts['book.close1']:clone())
local rest=im();polygon(rest,{{5,42},{17,39},{24,42},{24,45},{13,47},{5,45}},'b');polygon(rest,{{6,41},{17,38},{23,41},{13,44},{6,43}},'K');polygon(rest,{{7,41},{17,39},{21,41},{13,43}},'C');H.line(rest,6,44,13,46,pal,'B');put('book.rest.sleep',rest)
local zs={s={'ZZZ','..Z','ZZZ'},m={'ZZZZ','..Z.','.Z..','ZZZZ'},l={'ZZZZZ','...Z.','..Z..','.Z...','ZZZZZ'}}
for _,sz in ipairs({'s','m','l'}) do for _,c in ipairs({'Z','Y','X'}) do local z=im();H.stamp(z,zs[sz],0,0,pal,{map={Z=c}});put('fx.z.'..sz..'.'..c,z) end end
for i=1,4 do local f=im();local n=i<3 and i+1 or 4-i+1;H.line(f,0,n,n*2,n,pal,'q');H.line(f,n,0,n,n*2,pal,'q');H.px(f,n,n,pal,'Q');put('fx.sparkle'..i,f)
  local g=im();H.stamp(g,{'W','W'},24+i*2,15,pal);put('fx.glint'..i,g)
end
for i=1,8 do local f=im();local rows=i==1 and {'S'} or (i==2 and {'SS','SS'} or {'.K.','KSK','KWS','KSK','.K.'});H.stamp(f,rows,35,10+math.max(0,i-3),pal);put('fx.sweat.d'..i,f) end
local qm=im();H.stamp(qm,{'.KKK.','KWWWK','...WK','..KK.','..K..','.....','..K..'},43,17,pal);put('fx.q.mark',qm)
local paper=im();H.stamp(paper,{'CCC','CPC','CCC'},28,30,pal);put('fx.paper',paper)
local function saveParts(path,ps,ns,w,h)
  if app.fs.isFile(path) then print(path..': exists, not reseeded');return end
  local s=H.newSprite(w,h,pal,{'part'});local rec=H.recorder(s)
  for _,n in ipairs(ns) do rec:start(n);rec:frame(1000,{part=ps[n]});rec:stop() end
  rec:apply();H.assertPalette(s,pal);H.save(s,path);s:close()
end
saveParts(app.fs.joinPath(ART,'parts/worm-parts.aseprite'),parts,order,64,48)
local small={};local sn={}
local function sp(n,img) small[n]=img;sn[#sn+1]=n end
local sm=H.grid({'........KKKKKK....','.......KmmmmmmK...','......KmmmmmmmmK..','..KKKKmmmmKKKKKK..','.KmmmmKmmKmmmmmK..','KmmmmmmKKmmmmmmmK.','KmmmmmmKKmmmmmmmK.','KmmmmmmKKmmmmmmmKK','KmmmmmmKKmmmmmmmKK','.KmmmmKmmKmmmmmK..','..KKKK.KmmKKKKK...','........KmmmmK....','.........KmmmK....','.........KmmmmK...','..........KmmmmK..','...........KKKK...','..................','..................'},pal)
sp('body.rest',sm);local bob=H.image(18,18)
for it in sm:pixels() do local yy=it.y<=10 and it.y+1 or it.y;H.px(bob,it.x,yy,pal,it()) end
sp('body.bob',bob);sp('body.droop',bob:clone())
for _,v in ipairs({'center','left','right','blink','half','error'}) do
  local f=H.image(18,18)
  H.rect(f,2,5,4,4,pal,'m');H.rect(f,10,5,5,4,pal,'m')
  if v=='error' then require('error_eyes').small(function(x,y,k) H.px(f,x,y,pal,k) end)
  elseif v=='blink' then H.line(f,2,7,5,7,pal,'K');H.line(f,10,7,14,7,pal,'K')
  else local k='K';local dx=v=='left' and -1 or (v=='right' and 1 or 0)
    H.stamp(f,{'.K.','KKK','.K.'},3+math.min(0,dx),6,pal,{map={K=k}});H.stamp(f,{'.K.','KKK','.K.'},11+dx,6,pal,{map={K=k}})
    if v=='half' then H.line(f,2,5,5,5,pal,'K');H.line(f,10,5,14,5,pal,'K') end
  end
  sp('eyes.'..v,f)
end
local sb=H.image(18,18);H.stamp(sb,{'CCC.PCC','CPC.PCC','CCC.PPC','BBBBbbb'},0,12,pal);sp('book.open',sb)
local sb2=sb:clone();H.px(sb2,4,13,pal,'C');H.px(sb2,5,13,pal,'P');sp('book.page',sb2)
for i=1,2 do local b=H.image(18,18);H.px(b,14,11+i,pal,'m');sp('body.chew'..i,b) end
saveParts(app.fs.joinPath(ART,'parts/worm-small-parts.aseprite'),small,sn,18,18)
print('parts: seeded once; future corrections belong in the GUI')
