local H=require('ase_helpers');local R=require('room_common')
local ART=(app.params or {}).art or app.fs.joinPath(H.scriptDir(),'..');R.context(ART)
local s=H.newSprite(24,12,R.pal,{'mask'});local rec=H.recorder(s);local frames={}
for _,kind in ipairs({'chat','page','note','video','other'}) do
 rec:start(kind);for _,mask in ipairs({'body','light','shade'}) do
  local part='spine.'..kind..'.'..mask;rec:frame(1000,{mask=R.part(part,24,12)});frames[#frames+1]={parts={{part=part,x=0,y=0}},mask=mask}
 end;rec:stop()
end
rec:apply();R.finish(s,'room-spines',frames);print('spines: five kinds, three tint masks each')
