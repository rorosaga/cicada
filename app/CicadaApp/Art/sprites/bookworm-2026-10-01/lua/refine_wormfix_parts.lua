-- Second visual iteration: preserve the authored page curls over the corrected
-- open-book base, a readable incoming cover top and the reference tail cap.
-- This authoring record edits saved parts; the normal export pipeline does not run it.
local H=require('ase_helpers')
local ART=(app.params or {}).art or app.fs.joinPath(H.scriptDir(),'..')
local pal=H.paletteFromJson(app.fs.joinPath(ART,'palette.json'))
local s=app.open(app.fs.joinPath(ART,'parts/worm-parts.aseprite'))
local frames={};for _,t in ipairs(s.tags) do frames[t.name]=t.fromFrame.frameNumber end
local function get(n) return H.flatten(s,frames[n]) end
local function set(n,im) H.setCel(s,s.layers[1],frames[n],im) end
-- Exact moving-page differences from the pre-fix saved parts, registered at (8,30).
local curls={
{"......................","......................","......................","......................","...............PP.....","..............PC.CP...","..............P....CP.",".............P......P.",".............P.CCC.P..","............PCC....P..","............P..CCCP...","...........P.CC...P...","...........P....P.....","..............P.......","..........C.P........."},
{"......................","......................","...............PP.....","...............PCPP...","..............PCCCCP..","..............PC.CP...",".............P....P...",".............P...P....","............P..CC.....","............PCC.P.....","...........P..........","...........P.C........",".............P........","............P.........","..........CP.........."},
{"......................","..........PP..........","..........PPP.........","..........PCCP........","..........PCCP........","..........PCCP........","..........PCCP........","..........PC.P........",".............P........","......................",".............P........","............P.........","............P.........","...........P..........","..........CP.........."},
{"......................","......................","......PP..............","......PCCP............",".....CPCCP............",".....CCPCP............","......CPCCP...........","........PCP...........","....C...P.............",".....CCC.P............","...CC....P............",".....CCC.P............","...........P..........","...........P..........","..........CP.........."},
{"......................","......................","......................","......................","..PCP.................","...PCCP...............","....P.CCP.............",".....P..P.............","..CCC.P..P............",".....C.C.P............","..CCC..P..............",".....CCCP.............",".........P............","...........P..........",".........CCP.........."}
}
local edges={{{23,34},{27,36},{25,41},{19,44}},{{23,32},{26,34},{23,39},{19,44}},{{18,31},{20,33},{20,39},{19,44}},{{14,32},{16,33},{19,44},{11,40}},{{10,34},{15,36},{19,44},{9,41}}}
for i,grid in ipairs(curls) do
 local im=get('book.open');H.stamp(im,grid,8,30,pal)
 local points=edges[i];for j,p in ipairs(points) do local q=points[j%#points+1];H.line(im,p[1],p[2],q[1],q[2],pal,'P') end
 H.line(im,points[1][1],points[1][2],points[2][1],points[2][2],pal,'K')
 set('book.flip'..i,im)
end
-- Close1/2 inherited bare blue cover edges. Keep their geometry and add a
-- single silhouette outline, before the tilted close3 carries the rotation.
for i=1,2 do
 local n='book.close'..i;local im=get(n);local old=im:clone()
 local function at(x,y) if x<0 or x>=64 or y<0 or y>=48 then return 0 end;return old:getPixel(x,y) end
 for it in old:pixels() do if it()~=0 then local x,y=it.x,it.y
  if at(x-1,y)==0 or at(x+1,y)==0 or at(x,y-1)==0 or at(x,y+1)==0 then H.px(im,x,y,pal,'K') end
 end end
 set(n,im)
end
for i=2,3 do
 local im=H.image(64,48);local y=i==2 and 31 or 30;local h=i==2 and 3 or 6
 H.rect(im,12,y,10,h,pal,'K');H.rect(im,13,y+1,8,h-2,pal,'B')
 H.rect(im,13,y+1,1,h-2,pal,'H');H.rect(im,20,y+1,1,h-2,pal,'b')
 set('book.peek'..i,im)
end
for _,v in ipairs({'sit','sit.in1','sit.in2','sit.tail1','slump','slump.in1','slump.in2','crouch','stretch1','stretch2'}) do
 local n='body.'..v..'/tail';local im=get(n);local dy=v=='sit.tail1' and -1 or 0
 H.px(im,58,33+dy,pal,'K');H.px(im,59,33+dy,pal,0);set(n,im)
end
H.assertPalette(s,pal);H.save(s,app.fs.joinPath(ART,'parts/worm-parts.aseprite'));s:close()
print('Second saved-part iteration complete')
