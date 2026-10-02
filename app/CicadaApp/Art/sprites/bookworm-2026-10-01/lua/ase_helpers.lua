-- ase_helpers.lua — small, verified helper library for authoring pixel-art sprites in Aseprite Lua.
-- Verified 2026-10-01 against Aseprite 1.3.18.6-dev (app.apiVersion 41), headless:
--   /Applications/Aseprite.app/Contents/MacOS/aseprite -b [--script-param k=v ...] --script build.lua
-- Load it from a script in the same folder with:  local H = require('ase_helpers')
-- (Aseprite puts the running script's folder first on package.path.)
--
-- Conventions
--   * Sprites are RGB. Index 0 of the sprite palette is transparent; palette keys are 1-char strings.
--   * Every opaque pixel is alpha 255 and a palette colour (H.assertPalette checks it).
--   * Durations are integer milliseconds at this API; Aseprite stores whole ms (1..65535).
--   * Tags are created only AFTER all frames exist: appending a frame after a tag that ends on the
--     last frame silently grows that tag (verified). Use H.recorder, or call H.tag at the very end.

local H = {}
H.VERSION = '2026-10-01'

local pc = app.pixelColor

----------------------------------------------------------------------------------------------- colours
-- '#RRGGBB', 'RRGGBB' or '#RRGGBBAA' -> r, g, b, a
function H.hex(h)
  h = h:gsub('^#', '')
  assert(#h == 6 or #h == 8, 'bad hex colour: ' .. h)
  local r, g, b = tonumber(h:sub(1, 2), 16), tonumber(h:sub(3, 4), 16), tonumber(h:sub(5, 6), 16)
  local a = #h == 8 and tonumber(h:sub(7, 8), 16) or 255
  return r, g, b, a
end

-- Palette from a table. Accepts either an ordered list
--   { {'g', '#6FCF6A', 'body'}, {'o', '#2B2423', 'outline'}, ... }
-- or a map { g = {'#6FCF6A', 'body'}, ... } (keys then sorted for a stable order).
-- Returns pal = { keys = {...}, px = {key -> pixel u32}, color = {key -> Color}, index = {key -> 1..n},
--                 hex = {key -> '#RRGGBB'}, role = {key -> string} }
function H.palette(entries)
  local list = {}
  if entries[1] ~= nil then
    for _, e in ipairs(entries) do list[#list + 1] = { e[1], e[2], e[3] or '' } end
  else
    for k, v in pairs(entries) do list[#list + 1] = { k, v[1], v[2] or '' } end
    table.sort(list, function(a, b) return a[1] < b[1] end)
  end
  local pal = { keys = {}, px = {}, color = {}, index = {}, hex = {}, role = {} }
  for i, e in ipairs(list) do
    local k = e[1]
    assert(type(k) == 'string' and #k == 1 and k ~= '.' and k ~= ' ', 'palette key must be 1 char, not . or space: ' .. tostring(k))
    assert(pal.px[k] == nil, 'duplicate palette key ' .. k)
    local r, g, b, a = H.hex(e[2])
    pal.keys[i] = k
    pal.px[k] = pc.rgba(r, g, b, a)
    pal.color[k] = Color { r = r, g = g, b = b, a = a }
    pal.index[k] = i
    pal.hex[k] = string.format('#%02X%02X%02X', r, g, b)
    pal.role[k] = e[3]
  end
  return pal
end

-- Read { "colors": [ {"key": "g", "hex": "#6FCF6A", "role": "body"}, ... ] } (the shared palette file).
function H.paletteFromJson(path)
  local t = H.readJson(path)
  local entries = {}
  for _, c in ipairs(t.colors) do entries[#entries + 1] = { c.key, c.hex, c.role } end
  ------------------------------------------------------------------------------- additions (2026-10-01 spec)
-- Load one variant (tag) of a hand-drawn part file: the flattened Image of the tag's first frame. Parts are
-- registered on the full canvas (§3.4), so there is no anchor. Cached; opening a sprite per frame would be slow.
H._parts = {}
function H.loadPart(path, tagName)
  local key = path .. '#' .. tostring(tagName)
  local hit = H._parts[key]
  if hit then return hit end
  local spr = app.open(path)
  assert(spr, 'cannot open part file ' .. path)
  local frameNumber, found = 1, (tagName == nil)
  for _, t in ipairs(spr.tags) do
    if t.name == tagName then frameNumber = t.fromFrame.frameNumber; found = true end
  end
  assert(found, 'no tag ' .. tostring(tagName) .. ' in ' .. path)
  local im = H.flatten(spr, frameNumber)
  spr:close()
  H._parts[key] = im
  return im
end

-- Bounding box of opaque pixels as {x, y, w, h}, or nil.
function H.inkBounds(im)
  local x0, y0, x1, y1
  for it in im:pixels() do
    if pc.rgbaA(it()) > 0 then
      x0 = x0 and math.min(x0, it.x) or it.x; y0 = y0 and math.min(y0, it.y) or it.y
      x1 = x1 and math.max(x1, it.x) or it.x; y1 = y1 and math.max(y1, it.y) or it.y
    end
  end
  if not x0 then return nil end
  return { x = x0, y = y0, w = x1 - x0 + 1, h = y1 - y0 + 1 }
end

function H.unionRect(a, b)
  if not a then return b end
  if not b then return a end
  local x0, y0 = math.min(a.x, b.x), math.min(a.y, b.y)
  local x1, y1 = math.max(a.x + a.w, b.x + b.w), math.max(a.y + a.h, b.y + b.h)
  return { x = x0, y = y0, w = x1 - x0, h = y1 - y0 }
end

-- Union ink over every frame of a sprite (flattened).
function H.spriteInk(spr)
  local u
  for f = 1, #spr.frames do u = H.unionRect(u, H.inkBounds(H.flatten(spr, f))) end
  return u
end

-- Recolour: map is {fromKey -> toKey} in pal, applied in ONE pass from the original pixels, so a cyclic map
-- (cover1 -> cover2 -> cover3 -> cover1) never chains. Returns a new image. Verified: it(v) sets the pixel.
function H.recolor(im, pal, map)
  local px = {}
  for from, to in pairs(map) do px[pal.px[from]] = pal.px[to] end
  local out = im:clone()
  for it in out:pixels() do local to = px[it()]; if to then it(to) end end
  return out
end

-- A named slice on the whole sprite (one key). Verified: slice.name is settable and readable back.
function H.addSlice(spr, name, r)
  local s = spr:newSlice(Rectangle(r.x, r.y, r.w, r.h))
  s.name = name
  return s
end

local pal = H.palette(entries)
pal.derived = {}
if t.night then
  for _, ramp in pairs(t.night.ramps) do
    for _, hex in ipairs(ramp) do pal.derived[pc.rgba(H.hex(hex))] = true end
  end
  for _, hex in pairs(t.night.glyphs.question.colors) do pal.derived[pc.rgba(H.hex(hex))] = true end
end
if t.scenery then
  for _, ramp in pairs(t.scenery.ramps) do
    for _, hex in pairs(ramp) do pal.derived[pc.rgba(H.hex(hex))] = true end
  end
  for _, color in ipairs(t.scenery.colors) do pal.derived[pc.rgba(H.hex(color.hex))] = true end
end
if t.clock then
  for _, hex in pairs(t.clock.colors) do pal.derived[pc.rgba(H.hex(hex))] = true end
end
return pal
end

-- Install pal as the sprite palette: index 0 transparent, then the keys in order.
function H.applyPalette(spr, pal)
  local p = Palette(#pal.keys + 1)
  p:setColor(0, Color { r = 0, g = 0, b = 0, a = 0 })
  for i, k in ipairs(pal.keys) do p:setColor(i, pal.color[k]) end
  spr:setPalette(p)
end

-- Derived RGB sources need their actual colours in Aseprite's display/GIF palette.
-- These entries are declared output colours, not new one-character authoring keys.
function H.applyUsedPalette(spr)
  local used={};local pixels={}
  for _,cel in ipairs(spr.cels) do
    for p in cel.image:pixels() do
      if pc.rgbaA(p())>0 then used[p()]=true end
    end
  end
  for pixel in pairs(used) do pixels[#pixels+1]=pixel end
  table.sort(pixels)
  assert(#pixels<256,'source GIF palette exceeds 255 opaque colours')
  local palette=Palette(#pixels+1)
  palette:setColor(0,Color{r=0,g=0,b=0,a=0})
  for i,pixel in ipairs(pixels) do
    palette:setColor(i,Color{r=pc.rgbaR(pixel),g=pc.rgbaG(pixel),b=pc.rgbaB(pixel),a=255})
  end
  spr:setPalette(palette)
end

function H.writePaletteJson(path, pal, extra)
  local t = extra or {}
  t.colors = {}
  for _, k in ipairs(pal.keys) do t.colors[#t.colors + 1] = { key = k, hex = pal.hex[k], role = pal.role[k] } end
  H.writeJson(path, t)
end

----------------------------------------------------------------------------------------------- images
function H.image(w, h)
  local im = Image(w, h, ColorMode.RGB)
  im:clear() -- fully transparent
  return im
end

-- One pixel, bounds-checked. `key` is a palette key, or a raw pixel value (number).
function H.px(im, x, y, pal, key)
  if x < 0 or y < 0 or x >= im.width or y >= im.height then return end
  local v = type(key) == 'number' and key or pal.px[key]
  assert(v ~= nil, 'unknown palette key ' .. tostring(key))
  im:drawPixel(x, y, v) -- drawPixel REPLACES (no blending), so alpha stays exact
end

function H.erase(im, x, y)
  if x >= 0 and y >= 0 and x < im.width and y < im.height then im:drawPixel(x, y, 0) end
end

function H.rect(im, x, y, w, h, pal, key)
  for yy = y, y + h - 1 do for xx = x, x + w - 1 do H.px(im, xx, yy, pal, key) end end
end

-- Bresenham line, whole pixels, inclusive ends.
function H.line(im, x0, y0, x1, y1, pal, key)
  local dx, dy = math.abs(x1 - x0), -math.abs(y1 - y0)
  local sx, sy = x0 < x1 and 1 or -1, y0 < y1 and 1 or -1
  local err = dx + dy
  while true do
    H.px(im, x0, y0, pal, key)
    if x0 == x1 and y0 == y1 then break end
    local e2 = 2 * err
    if e2 >= dy then err = err + dy; x0 = x0 + sx end
    if e2 <= dx then err = err + dx; y0 = y0 + sy end
  end
end

-- Stamp a grid of strings (one char = one pixel = one palette key). '.' and ' ' are transparent
-- (left untouched); '_' ERASES (writes transparent). opts.map = {char -> key} remaps chars;
-- opts.flipX = true mirrors horizontally. Unknown chars raise an error (catches typos).
function H.stamp(im, rows, x, y, pal, opts)
  opts = opts or {}
  local w = 0
  for _, r in ipairs(rows) do if #r > w then w = #r end end
  for j, row in ipairs(rows) do
    for i = 1, #row do
      local ch = row:sub(i, i)
      local tx = opts.flipX and (x + w - i) or (x + i - 1)
      if ch == '_' then
        H.erase(im, tx, y + j - 1)
      elseif ch ~= '.' and ch ~= ' ' then
        local key = (opts.map and opts.map[ch]) or ch
        assert(pal.px[key] ~= nil, string.format('unknown char %q at row %d col %d', ch, j, i))
        H.px(im, tx, y + j - 1, pal, key)
      end
    end
  end
  return im
end

-- A new image sized to the grid (width = longest row).
function H.grid(rows, pal, opts)
  local w = 0
  for _, r in ipairs(rows) do if #r > w then w = #r end end
  ------------------------------------------------------------------------------- additions (2026-10-01 spec)
-- Load one variant (tag) of a hand-drawn part file: the flattened Image of the tag's first frame. Parts are
-- registered on the full canvas (§3.4), so there is no anchor. Cached; opening a sprite per frame would be slow.
H._parts = {}
function H.loadPart(path, tagName)
  local key = path .. '#' .. tostring(tagName)
  local hit = H._parts[key]
  if hit then return hit end
  local spr = app.open(path)
  assert(spr, 'cannot open part file ' .. path)
  local frameNumber, found = 1, (tagName == nil)
  for _, t in ipairs(spr.tags) do
    if t.name == tagName then frameNumber = t.fromFrame.frameNumber; found = true end
  end
  assert(found, 'no tag ' .. tostring(tagName) .. ' in ' .. path)
  local im = H.flatten(spr, frameNumber)
  spr:close()
  H._parts[key] = im
  return im
end

-- Bounding box of opaque pixels as {x, y, w, h}, or nil.
function H.inkBounds(im)
  local x0, y0, x1, y1
  for it in im:pixels() do
    if pc.rgbaA(it()) > 0 then
      x0 = x0 and math.min(x0, it.x) or it.x; y0 = y0 and math.min(y0, it.y) or it.y
      x1 = x1 and math.max(x1, it.x) or it.x; y1 = y1 and math.max(y1, it.y) or it.y
    end
  end
  if not x0 then return nil end
  return { x = x0, y = y0, w = x1 - x0 + 1, h = y1 - y0 + 1 }
end

function H.unionRect(a, b)
  if not a then return b end
  if not b then return a end
  local x0, y0 = math.min(a.x, b.x), math.min(a.y, b.y)
  local x1, y1 = math.max(a.x + a.w, b.x + b.w), math.max(a.y + a.h, b.y + b.h)
  return { x = x0, y = y0, w = x1 - x0, h = y1 - y0 }
end

-- Union ink over every frame of a sprite (flattened).
function H.spriteInk(spr)
  local u
  for f = 1, #spr.frames do u = H.unionRect(u, H.inkBounds(H.flatten(spr, f))) end
  return u
end

-- Recolour: map is {fromKey -> toKey} in pal, applied in ONE pass from the original pixels, so a cyclic map
-- (cover1 -> cover2 -> cover3 -> cover1) never chains. Returns a new image. Verified: it(v) sets the pixel.
function H.recolor(im, pal, map)
  local px = {}
  for from, to in pairs(map) do px[pal.px[from]] = pal.px[to] end
  local out = im:clone()
  for it in out:pixels() do local to = px[it()]; if to then it(to) end end
  return out
end

-- A named slice on the whole sprite (one key). Verified: slice.name is settable and readable back.
function H.addSlice(spr, name, r)
  local s = spr:newSlice(Rectangle(r.x, r.y, r.w, r.h))
  s.name = name
  return s
end

return H.stamp(H.image(w, #rows), rows, 0, 0, pal, opts)
end

-- Composite src over dst at (x, y). Transparent src pixels leave dst untouched (verified);
-- semi-transparent ones blend, so keep art binary-alpha.
function H.paste(dst, src, x, y)
  dst:drawImage(src, Point(x or 0, y or 0))
  return dst
end

-- Nearest-neighbour enlargement (Image:resize defaults to nearest; verified pixel-exact vs Pillow NEAREST).
function H.scaled(im, n)
  if n == nil or n == 1 then return im:clone() end
  local out = im:clone()
  out:resize { width = im.width * n, height = im.height * n, method = 'nearest' }
  return out
end

-- Snap an image to the palette: alpha < alphaCut (default 128) -> transparent, else the nearest
-- palette colour (squared RGB distance) at alpha 255. Use it to turn a painted/AI reference that was
-- nearest-downsampled to the grid into a palette-locked tracing base (then clean it by hand).
function H.quantize(im, pal, alphaCut)
  alphaCut = alphaCut or 128
  local out = H.image(im.width, im.height)
  local cache = {}
  for it in im:pixels() do
    local v = it()
    if pc.rgbaA(v) >= alphaCut then
      local rgb = v & 0x00FFFFFF
      local best = cache[rgb]
      if not best then
        local r, g, b = pc.rgbaR(v), pc.rgbaG(v), pc.rgbaB(v)
        local bestD = math.huge
        for _, k in ipairs(pal.keys) do
          local q = pal.px[k]
          local dr, dg, db = r - pc.rgbaR(q), g - pc.rgbaG(q), b - pc.rgbaB(q)
          local d = dr * dr + dg * dg + db * db
          if d < bestD then bestD, best = d, q end
        end
        cache[rgb] = best
      end
      out:drawPixel(it.x, it.y, best)
    end
  end
  return out
end

-- Load a PNG as a grid-sized tracing image: nearest-downsample to (w, h), then H.quantize when pal given.
function H.loadReference(path, w, h, pal)
  local im = Image { fromFile = path }
  im:resize { width = w, height = h, method = 'nearest' }
  if pal then ------------------------------------------------------------------------------- additions (2026-10-01 spec)
-- Load one variant (tag) of a hand-drawn part file: the flattened Image of the tag's first frame. Parts are
-- registered on the full canvas (§3.4), so there is no anchor. Cached; opening a sprite per frame would be slow.
H._parts = {}
function H.loadPart(path, tagName)
  local key = path .. '#' .. tostring(tagName)
  local hit = H._parts[key]
  if hit then return hit end
  local spr = app.open(path)
  assert(spr, 'cannot open part file ' .. path)
  local frameNumber, found = 1, (tagName == nil)
  for _, t in ipairs(spr.tags) do
    if t.name == tagName then frameNumber = t.fromFrame.frameNumber; found = true end
  end
  assert(found, 'no tag ' .. tostring(tagName) .. ' in ' .. path)
  local im = H.flatten(spr, frameNumber)
  spr:close()
  H._parts[key] = im
  return im
end

-- Bounding box of opaque pixels as {x, y, w, h}, or nil.
function H.inkBounds(im)
  local x0, y0, x1, y1
  for it in im:pixels() do
    if pc.rgbaA(it()) > 0 then
      x0 = x0 and math.min(x0, it.x) or it.x; y0 = y0 and math.min(y0, it.y) or it.y
      x1 = x1 and math.max(x1, it.x) or it.x; y1 = y1 and math.max(y1, it.y) or it.y
    end
  end
  if not x0 then return nil end
  return { x = x0, y = y0, w = x1 - x0 + 1, h = y1 - y0 + 1 }
end

function H.unionRect(a, b)
  if not a then return b end
  if not b then return a end
  local x0, y0 = math.min(a.x, b.x), math.min(a.y, b.y)
  local x1, y1 = math.max(a.x + a.w, b.x + b.w), math.max(a.y + a.h, b.y + b.h)
  return { x = x0, y = y0, w = x1 - x0, h = y1 - y0 }
end

-- Union ink over every frame of a sprite (flattened).
function H.spriteInk(spr)
  local u
  for f = 1, #spr.frames do u = H.unionRect(u, H.inkBounds(H.flatten(spr, f))) end
  return u
end

-- Recolour: map is {fromKey -> toKey} in pal, applied in ONE pass from the original pixels, so a cyclic map
-- (cover1 -> cover2 -> cover3 -> cover1) never chains. Returns a new image. Verified: it(v) sets the pixel.
function H.recolor(im, pal, map)
  local px = {}
  for from, to in pairs(map) do px[pal.px[from]] = pal.px[to] end
  local out = im:clone()
  for it in out:pixels() do local to = px[it()]; if to then it(to) end end
  return out
end

-- A named slice on the whole sprite (one key). Verified: slice.name is settable and readable back.
function H.addSlice(spr, name, r)
  local s = spr:newSlice(Rectangle(r.x, r.y, r.w, r.h))
  s.name = name
  return s
end

return H.quantize(im, pal) end
  return im
end

-- Flattened render of one frame (all visible layers), as a new Image.
function H.flatten(spr, frameNumber)
  local im = Image(spr.width, spr.height, spr.colorMode)
  im:clear()
  im:drawSprite(spr, frameNumber)
  return im
end

----------------------------------------------------------------------------------------------- sprites
local fresh = setmetatable({}, { __mode = 'k' }) -- sprites whose frame 1 is still unused

-- New RGB sprite with pal installed and the layer stack created back to front
-- (layerNames default {'base'}). Returns spr, layersByName.
function H.newSprite(w, h, pal, layerNames)
  local spr = Sprite(w, h, ColorMode.RGB)
  if pal then H.applyPalette(spr, pal) end
  local layers = H.layers(spr, layerNames or { 'base' })
  fresh[spr] = true
  return spr, layers
end

-- Top-level layer by name, or nil.
function H.findLayer(spr, name)
  for _, l in ipairs(spr.layers) do if l.name == name then return l end end
  return nil
end

-- Create the layer stack once, BACK TO FRONT: H.layers(spr, {'room', 'worm', 'book', 'fx'}).
-- The first name renames the sprite's existing bottom layer. Do this before adding frames: layers are
-- never created implicitly, because a Lua table's pairs() order is arbitrary and would scramble the
-- stack (verified: an implicit-create version produced glow/fly/lamp instead of lamp/fly/glow).
function H.layers(spr, names)
  local out = {}
  for i, name in ipairs(names) do
    local l = H.findLayer(spr, name)
    if not l then
      if i == 1 and #spr.layers == 1 then l = spr.layers[1] else l = spr:newLayer() end
      l.name = name
    end
    out[name] = l
  end
  return out
end

-- Existing top-level layer by name; raises if missing (create it with H.layers first).
function H.layer(spr, name)
  local l = H.findLayer(spr, name)
  assert(l, 'no layer named ' .. tostring(name) .. ' (create the stack with H.layers first)')
  return l
end

local function setDuration(frame, ms)
  assert(ms >= 1 and ms <= 65535, 'duration out of range (1..65535 ms): ' .. tostring(ms))
  -- +0.5 ms: Aseprite truncates seconds->ms through a float; plain ms/1000 loses 1 ms on 48 values
  -- between 1001 and 4095 (e.g. 1001 -> 1000). Verified 0 mismatches for 1..5000 with +0.5.
  frame.duration = (ms + 0.5) / 1000
end
H.setDuration = setDuration

function H.ms(frame) return math.floor(frame.duration * 1000 + 0.5) end

-- Put an image in a cel (replaces any existing cel). Image is copied by Aseprite (cels are never linked).
function H.setCel(spr, layerOrName, frameNumber, im, x, y)
  local layer = type(layerOrName) == 'string' and H.layer(spr, layerOrName) or layerOrName
  return spr:newCel(layer, frameNumber, im, Point(x or 0, y or 0))
end

-- Append a frame with a duration and optional cels { layerName = Image | {image=Image, x=, y=} }.
-- The first call on a sprite from H.newSprite reuses frame 1. Returns the frame number.
function H.addFrame(spr, ms, cels)
  local frame
  if fresh[spr] then
    fresh[spr] = nil
    frame = spr.frames[1]
  else
    frame = spr:newEmptyFrame() -- appends at the end (no cels)
  end
  setDuration(frame, ms)
  local n = frame.frameNumber
  for name, c in pairs(cels or {}) do
    if type(c) == 'table' and c.image then H.setCel(spr, name, n, c.image, c.x, c.y)
    else H.setCel(spr, name, n, c, 0, 0) end
  end
  return n
end

-- Append a copy of frame `src` (every layer's cel image cloned; not linked). ms defaults to src's.
function H.copyFrame(spr, src, ms)
  local srcFrame = spr.frames[src]
  assert(srcFrame, 'no frame ' .. tostring(src))
  local dur = ms or H.ms(srcFrame)
  fresh[spr] = nil
  local frame = spr:newEmptyFrame()
  setDuration(frame, dur)
  local function walk(layers)
    for _, l in ipairs(layers) do
      if l.isGroup then walk(l.layers)
      else
        local cel = l:cel(src)
        if cel then spr:newCel(l, frame.frameNumber, cel.image:clone(), cel.position) end
      end
    end
  end
  walk(spr.layers)
  return frame.frameNumber
end

local DIRS = { forward = AniDir.FORWARD, reverse = AniDir.REVERSE, pingpong = AniDir.PING_PONG,
               pingpong_reverse = AniDir.PING_PONG_REVERSE }

-- Create a tag over [from, to] (1-based, inclusive). opts: dir ('forward'|'reverse'|'pingpong'|
-- 'pingpong_reverse'), repeats (0 = infinite), color ('#RRGGBB'), data (string; exported as "data").
-- Call only after ALL frames are appended (see the header note).
function H.tag(spr, name, from, to, opts)
  opts = opts or {}
  assert(from >= 1 and to >= from and to <= #spr.frames, string.format('tag %s range %d..%d outside 1..%d', name, from, to, #spr.frames))
  local t = spr:newTag(from, to)
  t.name = name
  t.aniDir = DIRS[opts.dir or 'forward']
  if opts.repeats then t.repeats = opts.repeats end
  if opts.color then local r, g, b = H.hex(opts.color); t.color = Color { r = r, g = g, b = b } end
  if opts.data then t.data = opts.data end
  return t
end

-- Recorder: append frames under named tags, then create every tag at the end in one go.
--   local rec = H.recorder(spr)
--   rec:start('idle'); rec:frame(780, {body=img}); rec:copy(1, 90); rec:stop()
--   rec:apply()  -- creates the tags
function H.recorder(spr)
  local r = { spr = spr, ranges = {}, open = nil }
  function r:start(name, opts)
    assert(self.open == nil, 'tag ' .. tostring(self.open and self.open.name) .. ' still open')
    self.open = { name = name, opts = opts, from = nil }
  end
  local function note(self, n)
    if self.open then self.open.from = self.open.from or n; self.open.to = n end
    return n
  end
  function r:frame(ms, cels) return note(self, H.addFrame(self.spr, ms, cels)) end
  function r:copy(src, ms) return note(self, H.copyFrame(self.spr, src, ms)) end
  function r:stop()
    assert(self.open and self.open.from, 'stop() with no open tag or no frames')
    self.ranges[#self.ranges + 1] = self.open
    self.open = nil
  end
  function r:apply()
    assert(self.open == nil, 'apply() with an open tag')
    for _, t in ipairs(self.ranges) do H.tag(self.spr, t.name, t.from, t.to, t.opts) end
    return self.ranges
  end
  return r
end

----------------------------------------------------------------------------------------------- checks
-- Every cel pixel is alpha 0, or alpha 255 and a palette colour. Returns true or raises with the first offender.
function H.assertPalette(spr, pal)
  local allowed = {}
  for _, k in ipairs(pal.keys) do allowed[pal.px[k]] = true end
  for pixel in pairs(pal.derived or {}) do allowed[pixel] = true end
  for _, cel in ipairs(spr.cels) do
    local im = cel.image
    for it in im:pixels() do
      local v = it()
      local a = pc.rgbaA(v)
      if a ~= 0 and (a ~= 255 or not allowed[v]) then
        error(string.format('off-palette pixel #%02X%02X%02X a=%d on layer %q frame %d at %d,%d',
          pc.rgbaR(v), pc.rgbaG(v), pc.rgbaB(v), a, cel.layer.name, cel.frameNumber,
          it.x + cel.position.x, it.y + cel.position.y))
      end
    end
  end
  return true
end

----------------------------------------------------------------------------------------------- files
function H.writeJson(path, t)
  local f = assert(io.open(path, 'w'))
  f:write(json.encode(t)); f:write('\n'); f:close()
end

function H.readJson(path)
  local f = assert(io.open(path, 'r'))
  local s = f:read('a'); f:close()
  return json.decode(s) -- note: numbers come back as floats (100 -> 100.0)
end

-- Folder of the calling script (for paths next to it).
function H.scriptDir()
  local src = debug.getinfo(2, 'S').source
  return app.fs.filePath(src:sub(1, 1) == '@' and src:sub(2) or src)
end

function H.ensureDir(dir) app.fs.makeAllDirectories(dir) end

-- Save the layered source. saveAs changes spr.filename; use spr:saveCopyAs to keep it.
function H.save(spr, path)
  H.ensureDir(app.fs.filePath(path))
  spr:saveAs(path)
end

-- Packed sheet PNG + JSON array (frames + meta.frameTags/layers/slices) for the whole sprite.
-- opts: type ('packed'|'rows'|'columns'|'horizontal'|'vertical'), columns, trim (default false),
-- shapePadding, borderPadding, filenameFormat (e.g. '{tag}/{tagframe}').
-- Never pass a tag here if the JSON is consumed: meta.frameTags still lists every tag with
-- whole-sprite indices (verified), so the indices would not match the frames array.
function H.exportSheet(spr, pngPath, jsonPath, opts)
  opts = opts or {}
  local types = { packed = SpriteSheetType.PACKED, rows = SpriteSheetType.ROWS, columns = SpriteSheetType.COLUMNS,
                  horizontal = SpriteSheetType.HORIZONTAL, vertical = SpriteSheetType.VERTICAL }
  H.ensureDir(app.fs.filePath(pngPath))
  app.sprite = spr -- app.command.* acts on the active sprite
  app.command.ExportSpriteSheet {
    ui = false, askOverwrite = false,
    type = types[opts.type or 'packed'],
    columns = opts.columns or 0,
    textureFilename = pngPath,
    dataFilename = jsonPath,
    dataFormat = SpriteSheetDataFormat.JSON_ARRAY,
    filenameFormat = opts.filenameFormat,
    borderPadding = opts.borderPadding or 0, shapePadding = opts.shapePadding or 0, innerPadding = 0,
    trim = opts.trim or false, trimSprite = false, mergeDuplicates = opts.mergeDuplicates or false,
    ignoreEmpty = false, splitLayers = false, splitTags = false,
    listLayers = true, listTags = true, listSlices = true,
  }
end

-- Animated GIF of one tag (or the whole sprite when tag is nil) at an integer nearest-neighbour scale,
-- with the real per-frame durations, looping forever. Plays frames in timeline order: a tag's
-- direction/repeats are NOT applied (that needs --play-subtags on the CLI).
function H.exportGif(spr, path, tag, scale)
  H.ensureDir(app.fs.filePath(path))
  app.sprite = spr
  local p = { ui = false, filename = path, scale = scale or 1 }
  if tag then p.tag = tag end
  app.command.SaveFileCopyAs(p)
end

-- PNG of an Image at an integer nearest-neighbour scale (alpha kept).
-- (Two functions, not one: reading a field an object lacks, e.g. image.frames, RAISES
-- "Field frames does not exist" instead of returning nil — verified.)
function H.exportPng(im, path, scale)
  H.ensureDir(app.fs.filePath(path))
  H.scaled(im, scale or 1):saveAs(path)
end

-- PNG of one flattened sprite frame at an integer nearest-neighbour scale.
function H.exportFramePng(spr, frameNumber, path, scale)
  H.exportPng(H.flatten(spr, frameNumber), path, scale)
end

-- Summary table for a timings/ledger JSON: { tags = { {name, from, to (0-based like the sheet JSON),
-- durations_ms = {...}} }, frames = n }.
function H.ledger(spr)
  local out = { frames = #spr.frames, tags = {} }
  for _, t in ipairs(spr.tags) do
    local d = {}
    for f = t.fromFrame.frameNumber, t.toFrame.frameNumber do d[#d + 1] = H.ms(spr.frames[f]) end
    out.tags[#out.tags + 1] = { name = t.name, from = t.fromFrame.frameNumber - 1, to = t.toFrame.frameNumber - 1, durations_ms = d }
  end
  return out
end

------------------------------------------------------------------------------- additions (2026-10-01 spec)
-- Load one variant (tag) of a hand-drawn part file: the flattened Image of the tag's first frame. Parts are
-- registered on the full canvas (§3.4), so there is no anchor. Cached; opening a sprite per frame would be slow.
H._parts = {}
function H.loadPart(path, tagName)
  local key = path .. '#' .. tostring(tagName)
  local hit = H._parts[key]
  if hit then return hit end
  local spr = app.open(path)
  assert(spr, 'cannot open part file ' .. path)
  local frameNumber, found = 1, (tagName == nil)
  for _, t in ipairs(spr.tags) do
    if t.name == tagName then frameNumber = t.fromFrame.frameNumber; found = true end
  end
  assert(found, 'no tag ' .. tostring(tagName) .. ' in ' .. path)
  local im = H.flatten(spr, frameNumber)
  spr:close()
  H._parts[key] = im
  return im
end

-- Bounding box of opaque pixels as {x, y, w, h}, or nil.
function H.inkBounds(im)
  local x0, y0, x1, y1
  for it in im:pixels() do
    if pc.rgbaA(it()) > 0 then
      x0 = x0 and math.min(x0, it.x) or it.x; y0 = y0 and math.min(y0, it.y) or it.y
      x1 = x1 and math.max(x1, it.x) or it.x; y1 = y1 and math.max(y1, it.y) or it.y
    end
  end
  if not x0 then return nil end
  return { x = x0, y = y0, w = x1 - x0 + 1, h = y1 - y0 + 1 }
end

function H.unionRect(a, b)
  if not a then return b end
  if not b then return a end
  local x0, y0 = math.min(a.x, b.x), math.min(a.y, b.y)
  local x1, y1 = math.max(a.x + a.w, b.x + b.w), math.max(a.y + a.h, b.y + b.h)
  return { x = x0, y = y0, w = x1 - x0, h = y1 - y0 }
end

-- Union ink over every frame of a sprite (flattened).
function H.spriteInk(spr)
  local u
  for f = 1, #spr.frames do u = H.unionRect(u, H.inkBounds(H.flatten(spr, f))) end
  return u
end

-- Recolour: map is {fromKey -> toKey} in pal, applied in ONE pass from the original pixels, so a cyclic map
-- (cover1 -> cover2 -> cover3 -> cover1) never chains. Returns a new image. Verified: it(v) sets the pixel.
function H.recolor(im, pal, map)
  local px = {}
  for from, to in pairs(map) do px[pal.px[from]] = pal.px[to] end
  local out = im:clone()
  for it in out:pixels() do local to = px[it()]; if to then it(to) end end
  return out
end

-- A named slice on the whole sprite (one key). Verified: slice.name is settable and readable back.
function H.addSlice(spr, name, r)
  local s = spr:newSlice(Rectangle(r.x, r.y, r.w, r.h))
  s.name = name
  return s
end

return H
