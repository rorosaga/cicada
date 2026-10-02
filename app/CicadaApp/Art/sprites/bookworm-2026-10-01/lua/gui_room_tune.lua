-- GUI correction record. Native 1px Pencil / Eraser, never part of a rebuild.
assert(app.isUIAvailable,'GUI only')
local s=app.activeSprite;assert(s and s.filename:match('room%-parts.aseprite$'))
local root=app.fs.filePath(app.fs.filePath(debug.getinfo(1,'S').source:sub(2)))
local f=assert(io.open(app.fs.joinPath(root,'palette.json'),'r'));local palette=json.decode(f:read('a'));f:close()
local colors={};for _,c in ipairs(palette.colors) do colors[c.role]=Color{r=tonumber(c.hex:sub(2,3),16),g=tonumber(c.hex:sub(4,5),16),b=tonumber(c.hex:sub(6,7),16)} end
local function choose(name)
 for _,t in ipairs(s.tags) do if t.name==name then app.frame=t.fromFrame;app.layer=s.layers[1];return end end
 error('missing '..name)
end
local function dot(x,y,c) app.useTool{tool='pencil',brush=Brush(1),color=assert(colors[c]),points={Point(x,y)}} end
local function erase(x,y) app.useTool{tool='eraser',brush=Brush(1),points={Point(x,y)}} end
app.transaction('Refine room fabric, leaf silhouettes and lamp light',function()
 choose('plant')
 -- Connect the original isolated foliage into small readable leaf clusters.
 for _,p in ipairs({{4,1},{4,2},{5,3},{1,5},{2,5},{2,6},{3,6},{9,6},{10,6},{9,7},{8,8},{2,11},{3,11},{3,12},{9,12},{10,12},{9,13},{8,13}}) do dot(p[1],p[2],'room.leaf.1') end
 for _,p in ipairs({{3,1},{1,5},{9,5},{2,10},{9,11}}) do dot(p[1],p[2],'room.leaf.2') end
 choose('lamp.dark');dot(7,1,'room.lamp.2');dot(7,2,'room.lamp.2');dot(6,3,'room.lamp.2');dot(5,5,'room.lamp.2')
 choose('lamp.light');dot(5,9,'room.lampWarm.1');dot(6,9,'room.lampWarm.1');dot(7,9,'room.lampWarm.1');dot(12,10,'room.lampWarm.0')
 choose('bag');dot(5,3,'room.bag.2');dot(6,3,'room.bag.2');dot(56,3,'room.bag.2');dot(57,4,'room.bag.1');dot(11,8,'room.bag.1');dot(51,8,'room.bag.1')
 choose('glow')
 -- Break square corners into short 1:2 staircases in the three light rings.
 for _,p in ipairs({{3,10},{4,10},{24,10},{25,10},{0,14},{0,15},{28,14},{28,15},{3,33},{4,33},{24,33},{25,33},{0,29},{28,29},{3,13},{21,13},{0,17},{24,17},{3,30},{21,30},{0,26},{24,26},{4,16},{17,16},{1,20},{20,20},{4,27},{17,27},{1,23},{20,23}}) do erase(p[1],p[2]) end
 choose('window.sill');dot(2,35,'room.wood.2');dot(3,35,'room.wood.2')
 choose('mug');dot(1,3,'room.lampWarm.1')
 choose('cloud.round');dot(3,1,'cloud.1');dot(8,1,'cloud.1');erase(0,2);erase(11,2)
end)
app.command.SaveFile();choose('plant');app.command.Zoom{action='set',percentage=800};app.refresh()
