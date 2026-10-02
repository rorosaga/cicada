-- First version only. Never overwrites the saved GUI-corrected room parts.
local H=require('ase_helpers');local R=require('room_common')
local ART=(app.params or {}).art or app.fs.joinPath(H.scriptDir(),'..');R.context(ART)
local path=app.fs.joinPath(ART,'parts/room-parts.aseprite')
if app.fs.isFile(path) then print('room parts exist, not reseeded');return end
-- Aseprite has one canvas per document. All parts register at (0,0) on 110x64;
-- the builders crop to the named part's canvas. Extra area is always transparent.
local s=H.newSprite(110,64,R.pal,{'parts'});local rec=H.recorder(s)
local function save(name,im) rec:start(name);rec:frame(1000,{parts=im});rec:stop() end
local function im(w,h) return H.image(w,h) end
local function row(a,y,l,r,c) R.rect(a,l,y,r-l+1,1,c) end
-- Wall: plaster seams spaced deliberately, plain behind the sleeping glyphs.
local wall=im(110,64);R.rect(wall,0,0,110,54,'room.wall.0')
R.rect(wall,16,0,47,54,'room.wall.1')
for y=4,50,9 do for x=3,103,19 do
  if not(x>=76 and y<=21) then R.line(wall,x,y,x+3,y,'room.wall.2') end
end end
save('wall',wall)
local floor=im(110,64);R.rect(floor,0,56,110,8,'room.floor.0')
for y=56,63,4 do R.line(floor,0,y,107,y,'room.floor.2');R.line(floor,0,y+1,107,y+1,'room.floor.1') end
for _,p in ipairs({{17,57},{46,57},{80,57},{31,61},{65,61},{98,61}}) do R.line(floor,p[1],p[2],p[1],p[2]+2,'room.floor.2') end
-- Subdued woven rug, under the bag, no noisy dither.
for y=61,63 do row(floor,y,34+(y==61 and 2 or 0),100-(y==61 and 2 or 0),'room.bag.1') end
R.line(floor,35,62,99,62,'room.bag.2');save('floor',floor)
local trim=im(110,64);R.rect(trim,0,54,110,2,'room.wood.1');R.line(trim,0,54,107,54,'room.wood.2')
R.rect(trim,108,0,2,64,'room.wood.0');R.line(trim,108,0,108,53,'room.wood.2')
-- Outlet, cord and one soft bend on the floor.
R.rect(trim,11,52,3,3,'room.wall.1');R.px(trim,12,53,'room.lamp.0')
R.line(trim,12,54,12,60,'room.lamp.0');R.line(trim,5,61,11,61,'room.lamp.0');R.px(trim,4,60,'room.lamp.0');save('trim',trim)
-- Light pool is stepped opaque colour; only replaces wall/floor inside the pool.
local glow=im(110,64)
for _,q in ipairs({{0,10,29,24,'room.wall.1'},{0,13,25,18,'room.glow.0'},{1,16,20,12,'room.glow.1'}}) do
  local x,y,w,h,c=table.unpack(q);R.rect(glow,x+3,y,w-6,h,c);R.rect(glow,x,y+4,w,h-8,c)
end
row(glow,60,0,18,'room.glow.0');row(glow,61,0,22,'room.glow.0');row(glow,62,0,20,'room.glow.0');row(glow,63,0,17,'room.glow.0')
row(glow,61,2,14,'room.glow.1');row(glow,62,3,12,'room.glow.1');save('glow',glow)
local frame=im(40,38);R.rect(frame,0,0,40,34,'room.wood.0');R.rect(frame,1,1,38,32,'room.wood.2')
for y=2,33 do for x=2,37 do H.erase(frame,x,y) end end
R.rect(frame,19,2,2,32,'room.wood.0');R.line(frame,19,2,19,33,'room.wood.2')
R.rect(frame,2,17,36,2,'room.wood.0');R.line(frame,2,17,37,17,'room.wood.2')
save('window.frame',frame)
local sill=im(40,38);R.rect(sill,0,34,40,3,'room.wood.1');R.line(sill,0,34,39,34,'room.wood.2');R.line(sill,1,37,38,37,'room.wood.0');R.line(sill,1,35,38,35,'room.wood.2');save('window.sill',sill)
-- The shade is a cone with a low elliptic rim, steel edging and left-side light.
local lamp=im(18,50)
for y=0,9 do local l=6-math.floor(y/2);local rr=11+math.floor(y/2);row(lamp,y,l,rr,'room.lamp.0');if y>0 then row(lamp,y,l+1,rr-1,'room.lamp.1');R.px(lamp,l+1,y,'room.lamp.2') end end
row(lamp,10,2,15,'room.lamp.0');row(lamp,11,4,13,'room.lamp.0');row(lamp,10,4,13,'room.lamp.1')
R.rect(lamp,8,12,2,33,'room.lamp.0');R.line(lamp,8,12,8,44,'room.lamp.1')
row(lamp,45,6,11,'room.lamp.0');row(lamp,46,4,13,'room.lamp.0');row(lamp,47,3,14,'room.lamp.0');row(lamp,48,3,14,'room.lamp.0');row(lamp,49,5,12,'room.lamp.0')
row(lamp,46,6,11,'room.lamp.2');row(lamp,47,4,12,'room.lamp.1');save('lamp.dark',lamp)
local light=im(18,50)
row(light,9,3,14,'room.lampWarm.0');row(light,10,4,13,'room.lampWarm.0');row(light,11,6,11,'room.lampWarm.0');row(light,10,7,10,'room.lampWarm.1')
R.line(light,2,8,5,2,'room.lampWarm.0');R.px(light,6,1,'room.lampWarm.1');R.px(light,15,8,'room.lampWarm.0');save('lamp.light',light)
local bag=im(62,12)
local limits={{6,17},{3,58},{2,59},{1,60},{0,61},{0,61},{0,61},{1,60},{2,59},{3,58},{6,55},{10,51}}
for y=0,11 do local l,r=table.unpack(limits[y+1]);row(bag,y,l,r,'room.bag.0');if y>0 and y<10 then row(bag,y,l+1,r-1,'room.bag.1') end end
-- Two raised lobes, centre dip and a broad quiet cushion area under the base.
row(bag,1,6,16,'room.bag.2');row(bag,1,44,55,'room.bag.2');row(bag,2,4,17,'room.bag.2');row(bag,2,19,43,'room.bag.0');row(bag,2,45,57,'room.bag.2')
R.line(bag,7,4,11,8,'room.bag.0');R.line(bag,55,4,51,8,'room.bag.0');R.line(bag,13,9,48,9,'room.bag.0');save('bag',bag)
local plant=im(12,22);R.line(plant,6,5,6,15,'room.leaf.0');R.line(plant,6,10,2,6,'room.leaf.0');R.line(plant,6,12,10,8,'room.leaf.0')
local leaves={{{4,0},{3,1},{3,2},{4,3},{5,4},{6,4}},{{1,4},{0,5},{1,6},{2,7},{3,7},{4,8}},{{9,5},{10,5},{11,6},{10,7},{9,8},{8,9}},{{3,10},{2,10},{1,11},{2,12},{3,12},{4,13}},{{9,11},{10,11},{11,12},{10,13},{9,14},{7,14}}}
for _,leaf in ipairs(leaves) do for j,p in ipairs(leaf) do R.px(plant,p[1],p[2],j%3==1 and 'room.leaf.2' or 'room.leaf.1') end end
R.rect(plant,2,15,8,2,'room.wood.0');R.rect(plant,3,17,6,4,'room.pot.0');R.line(plant,4,21,7,21,'room.wood.0');R.line(plant,3,17,3,19,'room.pot.1');R.line(plant,2,15,8,15,'room.pot.1');save('plant',plant)
local mug=im(8,9);R.rect(mug,0,1,5,7,'room.mug.0');R.rect(mug,1,2,3,5,'room.mug.1');R.line(mug,1,8,3,8,'room.mug.0');R.line(mug,1,1,3,1,'room.lampWarm.1');R.line(mug,1,2,3,2,'room.wood.0');R.line(mug,5,2,6,2,'room.mug.0');R.line(mug,7,3,7,5,'room.mug.0');R.line(mug,5,6,6,6,'room.mug.0');save('mug',mug)
local cloud=im(12,4);row(cloud,0,4,7,'cloud.1');row(cloud,1,2,9,'cloud.1');row(cloud,2,0,11,'cloud.1');row(cloud,3,1,10,'cloud.0');save('cloud.round',cloud)
local thin=im(13,2);row(thin,0,3,8,'cloud.1');row(thin,1,0,12,'cloud.0');save('cloud.thin',thin)
-- Tree variants registered to the trunk. Canopy overlaps branch seams.
for lean=0,2 do local tree=im(14,14);R.line(tree,7,6,7,13,'room.wood.0');R.line(tree,7,8,4+lean,5,'room.wood.0');R.line(tree,7,9,10+lean,6,'room.wood.0')
  for y=0,7 do local l=(y<2 and 3 or (y<6 and 1 or 3))+lean;local rr=(y<2 and 8 or (y<6 and 11 or 9))+lean;row(tree,y,l,rr,'room.leaf.0');if y<6 then row(tree,y,l+1,rr-1,'room.leaf.1') end end
  R.line(tree,4+lean,1,7+lean,1,'room.leaf.2');R.line(tree,2+lean,3,6+lean,3,'room.leaf.2');save('tree.'..lean,tree)
end
-- Sun/moon stay in the clear upper-left pane. Rays are separately animated.
local sun=im(7,7);for y=0,6 do local l=(y==0 or y==6) and 2 or ((y==1 or y==5) and 1 or 0);row(sun,y,l,6-l,'celestial.sun.0') end
row(sun,1,2,4,'celestial.sun.1');row(sun,2,1,3,'celestial.sun.1');save('sun',sun)
local moon=im(7,8);H.stamp(moon,{'..aaa..','.aaa...','aaa....','aaa....','aaa....','.aaa..a','..aaaa.','...aa..'},0,0,R.pal,{map={a=R.key('celestial.moon.0')}});save('moon',moon)
-- Spine masks use one RGB value; tint belongs to the app. Top/bottom edge, plain centre.
for _,kind in ipairs({'chat','page','note','video','other'}) do
 local body=im(24,12);R.rect(body,0,1,24,10,'spine.mask.0');R.rect(body,1,0,23,12,'spine.mask.0');save('spine.'..kind..'.body',body)
 local hi=im(24,12);R.line(hi,1,0,23,0,'spine.mask.0');R.line(hi,0,1,0,10,'spine.mask.0')
 local sh=im(24,12);R.line(sh,1,11,23,11,'spine.mask.0')
 local marks={chat={'#.#.','#.#.','#.#.'},page={'.#.#','.##.','.#.#'},note={'#...','.#..','#...'},video={'####','#..#','####'},other={'###.','#.#.','###.'}}
 for j,r in ipairs(marks[kind]) do for x=1,4 do if r:sub(x,x)=='#' then R.px(hi,19+x,3+j,'spine.mask.0') end end end
 if kind=='chat' then for y=1,10 do R.px(hi,20,y,'spine.mask.0');R.px(hi,22,y,'spine.mask.0') end
 elseif kind=='page' then for y=1,10 do R.px(hi,23,y%2==0 and y or math.max(1,y-1),'spine.mask.0') end
 elseif kind=='note' then for y=1,10,2 do R.px(sh,21,y,'spine.mask.0') end
 elseif kind=='video' then R.px(sh,21,5,'spine.mask.0');R.px(sh,22,5,'spine.mask.0')
 else R.line(sh,20,7,22,7,'spine.mask.0') end
 save('spine.'..kind..'.light',hi);save('spine.'..kind..'.shade',sh)
end
rec:apply();H.assertPalette(s,R.pal);H.save(s,path);s:close();print('seeded room parts')
