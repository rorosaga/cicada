-- Second GUI iteration: diagonal z, final opening seam, and lowered book.
assert(app.isUIAvailable,'GUI only')
local s=app.activeSprite
assert(s.filename:match('worm%-parts.aseprite$'))
local function frame(n) for _,t in ipairs(s.tags) do if t.name==n then return t.fromFrame end end;error(n) end
local function select(n) app.frame=frame(n);app.layer=s.layers[1] end
local function stroke(x,y,c)
 app.useTool{tool=c.alpha==0 and 'eraser' or 'pencil',brush=Brush(1),color=c,points={Point(x,y)}}
end
local function color(px)
 return Color{r=app.pixelColor.rgbaR(px),g=app.pixelColor.rgbaG(px),b=app.pixelColor.rgbaB(px),a=app.pixelColor.rgbaA(px)}
end
local function image(n) return s.layers[1]:cel(frame(n)).image:clone() end
local function copyChanged(n,desired)
 select(n);local current=s.layers[1]:cel(app.frame);local im=current.image;local p=current.position
 for y=0,47 do for x=0,63 do
  local target=desired:getPixel(x,y);local old=(x>=p.x and y>=p.y and x<p.x+im.width and y<p.y+im.height) and im:getPixel(x-p.x,y-p.y) or 0
  if target~=old then stroke(x,y,color(target)) end
 end end
end
app.transaction('Refine diagonal z and book continuity',function()
 for _,v in ipairs({'Z','Y','X'}) do select('fx.z.s.'..v)
  local c=s.layers[1]:cel(app.frame).image:getPixel(0,0)
  stroke(1,1,color(c));stroke(2,1,Color{r=0,g=0,b=0,a=0})
 end
 -- Last opening pose is exactly the next cover's open key pose: no seam pop.
 local open=Image(64,48,ColorMode.RGB);local cel=s.layers[1]:cel(frame('book.open'));open:drawImage(cel.image,cel.position)
 copyChanged('book.open2',open)
 -- Lower by three while compressing the bottom six rows within the canvas.
 -- This keeps the spine intact before the body occludes it; no edge clipping.
 local closed=Image(64,48,ColorMode.RGB);cel=s.layers[1]:cel(frame('book.closed'));closed:drawImage(cel.image,cel.position)
 local low=Image(64,48,ColorMode.RGB)
 for y=0,47 do for x=0,61 do local c=closed:getPixel(x,y)
  if app.pixelColor.rgbaA(c)>0 then
   local yy=y<=41 and y+3 or (44+math.floor((y-42)/2));low:putPixel(x+2,math.min(47,yy),c)
  end
 end end
 copyChanged('book.closed.low',low)
end)
app.command.SaveFile();select('book.open2');app.editor.zoom=8;app.editor.scroll={x=20,y=36};app.refresh()
