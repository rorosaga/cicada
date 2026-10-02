-- Shared room authoring glue. The saved part file, not its seed, owns the pixels.
local H = require('ase_helpers')
local R = {H=H}
function R.context(dir)
  R.ART=dir;R.pal=H.paletteFromJson(app.fs.joinPath(dir,'palette.json'))
  R.roles={};for _,k in ipairs(R.pal.keys) do R.roles[R.pal.role[k]]=k end
  return R
end
function R.key(role) return assert(R.roles[role],'missing role '..role) end
function R.px(im,x,y,role) H.px(im,x,y,R.pal,R.key(role)) end
function R.rect(im,x,y,w,h,role) H.rect(im,x,y,w,h,R.pal,R.key(role)) end
function R.line(im,x,y,xx,yy,role) H.line(im,x,y,xx,yy,R.pal,R.key(role)) end
function R.part(name,w,h)
  local src=H.loadPart(app.fs.joinPath(R.ART,'parts/room-parts.aseprite'),name)
  local out=H.image(w,h);H.paste(out,src,0,0);return out
end
function R.diff(a,b)
  local im=H.image(a.width,a.height)
  for it in a:pixels() do if it()~=b:getPixel(it.x,it.y) then im:drawPixel(it.x,it.y,app.pixelColor.rgba(255,255,255,255)) end end
  return H.inkBounds(im)
end
function R.finish(s,name,frames)
  H.assertPalette(s,R.pal);H.save(s,app.fs.joinPath(R.ART,'src',name..'.aseprite'))
  local registryPath=app.fs.joinPath(R.ART,'qa/room-registry.json')
  local registry=app.fs.isFile(registryPath) and H.readJson(registryPath) or {sheets={}}
  local record={canvas={w=s.width,h=s.height},tags={}}
  for _,t in ipairs(s.tags) do
    local tag={name=t.name,frames={}}
    for i=t.fromFrame.frameNumber,t.toFrame.frameNumber do
      local f=frames[i] or {}
      if f.parts then
        table.sort(f.parts,function(a,b)
          local function key(p)return (p.layer or '')..'|'..(p.part or '')..'|'..tostring(p.x or 0)..'|'..tostring(p.y or 0) end
          return key(a)<key(b)
        end)
      end
      f.index=i-1;f.ms=H.ms(s.frames[i]);tag.frames[#tag.frames+1]=f
    end
    record.tags[#record.tags+1]=tag
  end
  registry.sheets[name]=record;H.writeJson(registryPath,registry);s:close()
end
return R
