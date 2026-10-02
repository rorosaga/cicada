-- Final GUI-only pixel corrections. Native 1px pencil/eraser; saved parts remain authoritative.
assert(app.isUIAvailable,'GUI only')
local s=app.activeSprite
local function find(n) for _,t in ipairs(s.tags) do if t.name==n then return t end end end
local function col(px) return Color{r=app.pixelColor.rgbaR(px),g=app.pixelColor.rgbaG(px),b=app.pixelColor.rgbaB(px),a=app.pixelColor.rgbaA(px)} end
local function draw(x,y,c) app.useTool{tool=c.alpha==0 and 'eraser' or 'pencil',brush=Brush(1),color=c,points={Point(x,y)}} end
local function full(n) local im=Image(s.width,s.height,ColorMode.RGB);local cel=s.layers[1]:cel(find(n).fromFrame);im:drawImage(cel.image,cel.position);return im end
local function create(n,source)
 if not find(n) then local f=s:newEmptyFrame();s:newCel(s.layers[1],f,full(source));local t=s:newTag(f,f);t.name=n end
 app.frame=find(n).fromFrame;app.layer=s.layers[1]
end
local K=Color{r=9,g=7,b=7,a=255}
-- Colour entries are sampled from existing saved pixels rather than invented.
app.transaction('Tail settle and farther glances',function()
 create('body.sit.tailhalf/tail','body.sit.tail1/tail')
 local rest=full('body.sit/tail');local lifted=full('body.sit.tail1/tail')
 -- Return the tip's brightest shoulder one palette step before the contour settles.
 local shade
 for it in rest:pixels() do local px=it();if app.pixelColor.rgbaA(px)>0 and app.pixelColor.rgbaR(px)>0 and app.pixelColor.rgbaR(px)<140 and app.pixelColor.rgbaG(px)>80 then shade=col(px);break end end
 assert(shade)
 for y=29,47 do for x=48,63 do draw(x,y,col(lifted:getPixel(x,y))) end end
 for _,p in ipairs({{55,33},{56,34},{57,34}}) do if lifted:getPixel(p[1],p[2])~=0 then draw(p[1],p[2],shade) end end
 for _,v in ipairs({'left','right','up.left','up.right'}) do
  create('eyes.'..v..'.far','eyes.'..v)
  local old=full('eyes.'..v);local dx=v:find('left') and -1 or 1
  local green=col(old:getPixel(29,24));local pupils={}
  for y=18,24 do for x=23,29 do if old:getPixel(x,y)==app.pixelColor.rgba(9,7,7,255) then pupils[#pupils+1]={x,y} end end end
  for _,p in ipairs(pupils) do draw(p[1],p[2],green) end
  for _,p in ipairs(pupils) do draw(p[1]+dx,p[2],K) end
 end
end)
app.command.SaveFile();app.editor.zoom=8;app.refresh()
