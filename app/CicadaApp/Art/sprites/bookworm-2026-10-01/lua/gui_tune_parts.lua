-- Manual correction log, executed ONLY in the GUI. Never part of export_all.sh.
-- Each point was selected after inspecting the part at high zoom. Uses the native
-- one-pixel Pencil, not Image:putPixel. The saved parts are authoritative.
assert(app.isUIAvailable, 'GUI-only correction session')
local s=app.activeSprite
assert(s and s.filename:match('worm%-parts.aseprite$'))
local C={G=Color{r=156,g=196,b=96},L=Color{r=133,g=129,b=130},K=Color{r=9,g=7,b=7},P=Color{r=188,g=184,b=180},C=Color{r=254,g=247,b=236}}
local function choose(name)
  for _,t in ipairs(s.tags) do if t.name==name then app.frame=t.fromFrame;app.layer=s.layers[1];return end end
  error('missing '..name)
end
local function dot(x,y,k)
  app.useTool{tool='pencil',brush=Brush(1),color=C[k],points={Point(x,y)}}
end
app.transaction('Hand clean pupils, frame light and turning page',function()
  -- Remove the temporary test specular; room speculars live only in eyes.*.
  choose('body.sit/head');dot(25,19,'G');dot(26,19,'G')
  for _,v in ipairs({'sit','sit.in1','sit.in2','sit.tail1','slump','slump.in1','slump.in2','crouch','stretch1','stretch2'}) do
    choose('body.'..v..'/head')
    local dy=v:find('slump') and 2 or (v=='crouch' and 1 or (v=='stretch1' and -1 or (v=='stretch2' and -2 or 0)))
    if v:find('in2') then dy=dy-1 end
    dot(34,19+dy,'L') -- carry the upper-left light onto the temple arm
  end
  -- Narrow four-wide pluses into precise 3x3 pluses, wholly inside lensR.
  for _,t in ipairs(s.tags) do if t.name:match('^eyes%.') and not t.name:find('closed') and not t.name:find('happy') then
    local n=t.name:sub(6);choose(t.name)
    local dx=n:find('left') and -1 or (n:find('right') and 1 or 0)
    local row=n:match('down%.l(%d)');if row then dx=tonumber(row)-2 end
    local dy=n:find('up') and -1 or (n:find('c$') and 1 or 0)
    -- All old pupil pixels are below the specular; preserve lids in half variants.
    if n~='half' and n~='blink.half' then
      for y=20,24 do for x=24,29 do dot(x,y,'G') end end
      local x=26+dx; local y=21+dy
      local k=n:find('error') and Color{r=229,g=72,b=77} or C.K
      for _,p in ipairs({{1,0},{0,1},{1,1},{2,1},{1,2}}) do
        app.useTool{tool='pencil',brush=Brush(1),color=k,points={Point(x+p[1],y+p[2])}}
      end
    end
  end end
  -- Round the worried brow's inner tip and soften the page curl's squared corner.
  choose('brows.worried');dot(26,11,'K')
  choose('brows.worried+1');dot(26,10,'K')
  choose('book.flip2');dot(25,33,'P');dot(24,33,'C')
  choose('book.flip3');dot(19,32,'P');dot(20,33,'C')
  choose('book.flip4');dot(14,34,'P');dot(15,34,'C')
end)
app.command.SaveFile()
choose('book.flip3')
app.refresh()
