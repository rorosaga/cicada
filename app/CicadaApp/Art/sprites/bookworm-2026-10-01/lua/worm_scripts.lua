-- Frame scripts are data after expansion: ms and registered parts (layer, tag, x, y).
local S={states={'awake','reading','sleeping','digesting','happy','hungry','error','curious'},sheets={}}
S.common={'idle','attentive.left','attentive.center','attentive.right','expectant.left','expectant.center','expectant.right','eager','perk.left','perk.center','perk.right','talk.left','talk.center','talk.right','gulp.center','shake.left','shake.center','shake.right'}
S.slices={eye={x=27,y=21,w=2,h=2},lensL={x=12,y=17,w=3,h=6},lensR={x=24,y=18,w=6,h=7}}
local rest={awake={'none','center','closed','none'},reading={'none','down.l0','open','none'},happy={'happy','center','closed','none'},hungry={'tired','half','closed','none'},digesting={'happy','happy','closed','chew1'},sleeping={'none','closed','rest.sleep','none'},error={'worried','error','closed','none'},curious={'curious','center','closed','none'}}
local function f(state,ms,o)
  o=o or {};local r=rest[state];local v=o.body or (state=='sleeping' and 'slump' or 'sit')
  local lift=o.lift or 0;local hx=o.hx or 0;local hy=o.hy or 0
  if v:find('slump') then hy=hy+2 end
  if v=='crouch' then hy=hy+1 elseif v=='stretch1' then hy=hy-1 elseif v=='stretch2' then hy=hy-2 end
  if v:find('in2') then hy=hy-1 end
  local parts={};local function add(layer,tag,x,y) parts[#parts+1]={layer=layer,tag=tag,x=x or 0,y=(y or 0)-lift} end
  local book=o.book or r[3]
  if o.back then add('book-back','book.'..book) end
  add('body','body.'..v..'/torso',o.tx or 0,o.ty or 0)
  add('body','body.'..(o.tail or v)..'/tail',o.ax or 0,o.ay or 0)
  add('body','body.'..v..'/head',hx,o.hy or 0)
  if not o.back then add('book','book.'..book) end
  if o.next then add('book-back','book.'..o.next,0,0);parts[#parts].remap=1 end
  add('face','eyes.'..(o.eyes or r[2]),hx,hy)
  add('brows','brows.'..(o.brows or r[1]),hx,hy)
  add('mouth','mouth.'..(o.mouth or r[4]),hx,hy)
  if state=='error' then add('fx','fx.sweat.'..(o.drop or 'd3'),hx,hy) end
  if state=='curious' then add('fx','fx.q.mark',0,o.qy or 0) end
  for _,fx in ipairs(o.fx or {}) do add('fx',fx[1],fx[2],fx[3]) end
  return {ms=ms,parts=parts,body=v,eyes=o.eyes or r[2],note=o.note}
end
local function seq(state,t)
  local out={};for _,v in ipairs(t) do out[#out+1]=f(state,v[1],v[2]) end;return out
end
S.sheets.awake={idle=seq('awake',{{700},{180,{body='sit.in1'}},{220,{body='sit.in2'}},{600,{body='sit.in2'}},{180,{hy=-1}},{260},{900},{60,{eyes='blink.half'}},{90,{eyes='closed'}},{60,{eyes='blink.half'}},{500},{180,{body='sit.in1'}},{220,{body='sit.in2'}},{700,{body='sit.in2'}},{180,{hy=-1}},{260},{600},{120,{body='sit.tail1'}},{120,{tail='sit.tailhalf'}},{700},{90,{eyes='closed'}},{120},{90,{eyes='closed'}},{1570},{60,{eyes='blink.half'}},{90,{eyes='closed'}},{60,{eyes='blink.half'}},{1400},{180,{body='sit.in1'}},{220,{body='sit.in2'}},{600,{body='sit.in2'}},{180,{hy=-1}},{260},{1450}})}
S.sheets.happy={idle=seq('happy',{{700},{180,{body='sit.in1'}},{220,{body='sit.in2'}},{600,{body='sit.in2'}},{180,{hy=-1}},{260},{200},{60,{eyes='blink.half'}},{90,{eyes='closed'}},{60,{eyes='blink.half'}},{290},{70,{fx={{'fx.glint1'}}}},{70,{fx={{'fx.glint2'}}}},{70,{fx={{'fx.glint3'}}}},{70,{fx={{'fx.glint4'}}}},{600},{60,{eyes='blink.half'}},{90,{eyes='closed'}},{60,{eyes='blink.half'}},{500},{180,{body='sit.in1'}},{220,{body='sit.in2'}},{700,{body='sit.in2'}},{180,{hy=-1}},{260},{300,{hx=1}},{900}})}
S.sheets.hungry={idle=seq('hungry',{{900},{260,{body='sit.in1'}},{300,{body='sit.in2'}},{800,{body='sit.in2'}},{260,{hy=-1}},{360},{700},{400,{hy=1}},{1200,{hy=1,eyes='closed'}},{120,{brows='tired+1'}},{800},{300,{eyes='closed'}},{600},{200,{mouth='talk1'}},{500,{mouth='yawn',eyes='closed',hy=-1}},{200,{mouth='talk1'}},{900}})}
S.sheets.error={idle=seq('error',{{300},{150,{drop='d4'}},{150,{drop='d5'}},{150,{drop='d6'}},{150,{drop='d7'}},{120,{drop='d8',fx={{'fx.sweat.d1'}}}},{200,{drop='d2'}},{300},{80,{hx=-1}},{80,{hx=1}},{80,{hx=-1}},{300},{340,{eyes='error.left'}}})}
S.sheets.curious={idle=seq('curious',{{600},{90,{eyes='closed'}},{210},{300,{qy=-1}},{600,{hx=1,hy=1,qy=-1}},{300,{hx=1,hy=1}},{1300},{200,{eyes='closed'}}})}
S.sheets.digesting={idle=seq('digesting',{{140},{140,{mouth='chew2',hy=1}},{140},{140,{mouth='chew2',hy=1}},{200,{mouth='none',fx={{'fx.bulge.high'}}}},{300,{mouth='smile'}}})}
local sleep={}
for i=1,32 do
  local phase=(i-1)%16+1;local body=phase>=5 and phase<=9 and 'slump.in2' or (phase>=4 and phase<=10 and 'slump.in1' or 'slump')
  local fx={};local function z(sz,c,x,y) fx[#fx+1]={'fx.z.'..sz..'.'..c,x,y} end
  if i<=10 then z('s',i<=6 and 'Z' or (i<=8 and 'Y' or 'X'),40+math.floor((i-1)/2),12-(i-1)) end
  if i>=9 and i<=20 then local t=i-9;local c=i<=15 and 'Z' or (i<=18 and 'Y' or 'X');local x,y=43+math.floor(t/2),11-math.floor(t/2);z('m',c,x,y);z('m',c,x+5,y-5) end
  if i>=19 then local t=i-19;local c=i<=26 and 'Z' or (i<=29 and 'Y' or 'X');local x=42+math.floor(t/3);z('s',c,x,11);if t>=2 then z('m',c,x+4,6) end;if t>=4 then z('l',c,x+9,0) end end
  sleep[#sleep+1]=f('sleeping',250,{body=body,fx=fx})
end
S.sheets.sleeping={idle=sleep,['talk.center']=seq('sleeping',{{90,{mouth='mumble1'}},{90},{90,{mouth='mumble2'}},{90},{90,{mouth='mumble1',fx={{'fx.z.s.Y',40,12}}}},{90}}),intro=seq('sleeping',{{140,{body='sit',eyes='half',book='close3'}},{120,{body='sit',eyes='half',book='closed',mouth='talk1'}},{260,{body='sit',eyes='closed',book='closed',mouth='yawn',hy=-1}},{200,{body='sit',book='closed',mouth='yawn'}},{120,{body='sit',book='closed',mouth='talk1'}},{120,{body='sit',book='closed'}},{120,{hy=-1,book='closed'}},{120,{hy=-1}},{120},{100}}),outro=seq('sleeping',{{120,{body='stretch1'}},{160,{body='stretch2',eyes='blink.half'}},{160,{body='stretch2',eyes='center',mouth='talk1'}},{240,{body='stretch2',eyes='closed',mouth='yawn'}},{140,{body='stretch1',eyes='half'}},{100,{body='sit',eyes='blink.half',book='closed'}},{80,{body='sit',eyes='closed',book='closed'}},{120,{body='sit',eyes='center',book='closed'}},{120,{body='sit',eyes='center',book='closed'}}})}
local read={};local line=0
local function L()
  local suffix=line%3==0 and '' or (line%3==1 and 'b' or 'c');line=line+1
  for i,ms in ipairs({420,380,380,420}) do read[#read+1]=f('reading',ms,{eyes='down.l'..(i-1)..suffix,note='line.'..line}) end
  read[#read+1]=f('reading',140,{eyes='down.l0'..(line%3==0 and '' or (line%3==1 and 'b' or 'c')),hy=1,note='line.return'})
end
local function Bk() read[#read+1]=f('reading',90,{eyes='closed'});read[#read+1]=f('reading',200) end
local function F() for i,ms in ipairs({90,90,100,90,120}) do read[#read+1]=f('reading',ms,{book='flip'..i,eyes=i<=2 and 'down.l3' or (i==3 and 'up' or 'down.l0'),note='flip.'..i}) end;read[#read+1]=f('reading',200,{note='flip.settle'}) end
L();L();L();Bk();F();L();Bk();L();F();L();L();L();F();L();Bk();L()
for i,ms in ipairs({100,120,140}) do read[#read+1]=f('reading',ms,{book='close'..i,note='close.'..i}) end
for i=1,3 do read[#read+1]=f('reading',140,{book='down'..i,back=true,next=i>=2 and 'up1' or nil,note='swap.down.'..i}) end
for i=1,3 do local a=f('reading',140,{book='up'..i,back=true,note='swap.up.'..i});for _,p in ipairs(a.parts) do if p.tag:find('book.') then p.remap=1 end end;read[#read+1]=a end
for i,ms in ipairs({140,160}) do local a=f('reading',ms,{book='open'..i,note='swap.open.'..i});for _,p in ipairs(a.parts) do if p.tag:find('book.') then p.remap=1 end end;read[#read+1]=a end
S.sheets.reading={idle=read}
local function gazeOptions(state,g)
  local e=state=='reading' and 'up' or (state=='hungry' and 'half' or (state=='digesting' and 'happy' or 'center'))
  if g~='center' and state~='hungry' and state~='digesting' then e=state=='reading' and ('up.'..g) or g end
  return {eyes=e,hx=g=='left' and -1 or (g=='right' and 1 or 0)}
end
local function options(base,changes) local out={};for k,v in pairs(base) do out[k]=v end;for k,v in pairs(changes or {}) do out[k]=v end;return out end
local function looks(state,tags)
  local sheet=S.sheets[state]
  for _,name in ipairs(tags) do if name~='idle' then
    local family,g=name:match('^(%a+)%.(%a+)$');family=family or name;g=g or 'center'
    local base=gazeOptions(state,g);local frames={}
    local function add(ms,o) frames[#frames+1]=f(state,ms,options(base,o)) end
    local happyBrows=rest[state][1];local raised=happyBrows..'+1'
    if family=='attentive' then
      add(1400);add(50,{eyes='blink.half'});add(state=='hungry' and 160 or 80,{eyes='closed'});add(50,{eyes='blink.half'});add(1250);add(300,{eyes=state=='hungry' and 'half' or (g=='center' and 'up' or (base.eyes..'.far'))});add(300);add(50,{eyes='blink.half'});add(state=='hungry' and 160 or 80,{eyes='closed'});add(50,{eyes='blink.half'});add(2300)
    elseif family=='expectant' then for i,ms in ipairs({240,140,140,200}) do add(ms,{mouth='talk2',brows=raised,body=i==2 and 'crouch' or 'sit'}) end
    elseif family=='eager' then for i,ms in ipairs({100,120,100,140}) do add(ms,{mouth='gulpOpen',brows=raised,body=(i==1 or i==4) and 'crouch' or 'sit',lift=i==2 and 2 or (i==3 and 1 or 0)}) end
    elseif family=='perk' then for i,ms in ipairs({60,80,120,100}) do add(ms,{body=i==1 and 'crouch' or 'sit',lift=i==2 and 2 or (i==3 and 1 or 0),brows=i==1 and happyBrows or raised,eyes=i==1 and base.eyes or 'wide'}) end
    elseif family=='talk' then for i,ms in ipairs({80,70,90,70,90,100}) do add(ms,{mouth=({'talk1','none','talk2','talk1','talk2','none'})[i],hy=(i==3 or i==5) and -1 or 0}) end
    elseif family=='gulp' then for i,ms in ipairs({90,90,80,90,90,90,120}) do add(ms,{mouth=i<=2 and 'gulpOpen' or (i==3 and 'talk1' or (i==7 and 'smile' or 'none')),book=state=='reading' and (i<=6 and 'closed.low' or 'open') or rest[state][3],back=state=='reading' and i<=6,fx=i==2 and {{'fx.paper'}} or (i>=4 and i<=6 and {{'fx.bulge.'..({'high','mid','low'})[i-3]}} or {})}) end
    elseif family=='shake' then for i,ms in ipairs({70,70,70,70,150}) do add(ms,{brows='sad',hx=i<5 and (i%2==1 and -1 or 1) or 0}) end
    elseif family=='cheer' then for i,ms in ipairs({100,100,120,100,100,80,120}) do add(ms,{body=(i==1 or i==6) and 'crouch' or 'sit',lift=({0,2,3,2,0,0,0})[i],eyes=i>=2 and i<=5 and 'happy' or rest[state][2],brows='happy',fx=i>=2 and i<=5 and {{'fx.sparkle'..(i-1),40,16}} or {}}) end
    else error('unknown look '..name) end
    sheet[name]=frames
  end end
end
for _,state in ipairs({'awake','reading','happy','hungry'}) do looks(state,S.common) end
looks('happy',{'cheer.center'});looks('digesting',{'expectant.center','eager','talk.center','gulp.center','shake.center','cheer.center'})
S.order={}
for _,state in ipairs(S.states) do
  local names={};if state=='awake' or state=='reading' or state=='happy' or state=='hungry' then for _,n in ipairs(S.common) do names[#names+1]=n end;if state=='happy' then names[#names+1]='cheer.center' end
  elseif state=='digesting' then names={'idle','expectant.center','eager','talk.center','gulp.center','shake.center','cheer.center'} elseif state=='sleeping' then names={'idle','talk.center','intro','outro'} else names={'idle'} end
  S.order[state]=names
end
return S
