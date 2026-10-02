assert(app.isUIAvailable,'GUI-only corrections')
local s=app.activeSprite
assert(s and s.filename:match('worm%-small%-parts.aseprite$'))
local function choose(n) for _,t in ipairs(s.tags) do if t.name==n then app.frame=t.fromFrame;return end end;error(n) end
local function dot(x,y,c) app.useTool{tool='pencil',brush=Brush(1),color=c,points={Point(x,y)}} end
local k=Color{r=9,g=7,b=7};local m=Color{r=172,g=236,b=98}
app.transaction('Clean neck step and preserve crown curve',function()
 for _,v in ipairs({'rest','bob','droop'}) do choose('body.'..v);dot(14,14,m);dot(15,14,k) end
 choose('book.page');dot(4,13,Color{r=188,g=184,b=180});dot(4,12,Color{r=254,g=247,b=236})
end)
app.command.SaveFile();choose('eyes.center');app.editor.zoom=8;app.editor.scroll={x=9,y=8};app.refresh()
