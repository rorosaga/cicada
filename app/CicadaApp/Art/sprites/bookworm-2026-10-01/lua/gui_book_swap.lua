-- GUI-only fourth book iteration: actual lowering/rising, within row 47.
assert(app.isUIAvailable,'GUI only')
local s=app.activeSprite;assert(s.filename:match('worm%-parts.aseprite$'))
local function frame(n) for _,t in ipairs(s.tags) do if t.name==n then return t.fromFrame end end;error(n) end
local function full(n) local im=Image(64,48,ColorMode.RGB);local c=s.layers[1]:cel(frame(n));im:drawImage(c.image,c.position);return im end
local function color(px) return Color{r=app.pixelColor.rgbaR(px),g=app.pixelColor.rgbaG(px),b=app.pixelColor.rgbaB(px),a=app.pixelColor.rgbaA(px)} end
local closed=full('book.closed')
local function replace(n,dx,dy)
 local desired=Image(64,48,ColorMode.RGB)
 for y=0,47 do for x=0,63 do local px=closed:getPixel(x,y)
  if app.pixelColor.rgbaA(px)>0 then
   -- Remap the whole contour into available height; no pixel is cut off.
   local yy=26+dy+math.floor((y-26)*(21-dy)/21+0.5)
   desired:putPixel(x+dx,yy,px)
  end
 end end
 app.frame=frame(n);app.layer=s.layers[1];local old=full(n)
 for y=0,47 do for x=0,63 do local px=desired:getPixel(x,y)
  if px~=old:getPixel(x,y) then local c=color(px);app.useTool{tool=c.alpha==0 and 'eraser' or 'pencil',brush=Brush(1),color=c,points={Point(x,y)}} end
 end end
end
app.transaction('Lower and raise books behind torso',function()
 for i=1,3 do replace('book.down'..i,4+i*2,i*2);replace('book.up'..i,10-i*3,(3-i)*2) end
end)
app.command.SaveFile();app.frame=frame('book.down2');app.editor.zoom=8;app.editor.scroll={x=20,y=36};app.refresh()
