// Execute the shipped inline script without a browser or network. This checks
// runtime/control wiring; it does not claim to validate browser Canvas pixels.
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';

const art=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const html=fs.readFileSync(path.join(art,'preview.html'),'utf8');
assert(!/\b(?:src|href)="https?:\/\//.test(html),'Preview must have no remote dependencies');
for(const match of html.matchAll(/\bsrc="([^"]+)"/g))
  assert(fs.existsSync(path.resolve(art,match[1])),`Missing relative image ${match[1]}`);
let draws=0;
const ctx={imageSmoothingEnabled:false,drawImage(){draws++},fillRect(){},fillText(){}};
class Element {
  constructor(){this.children=[];this.style={};this.value='';this.checked=false;this.hidden=false;this.width=0;this.height=0;}
  append(...items){this.children.push(...items);if(this.kind==='select'&&!this.value&&items[0])this.value=items[0].value;}
  replaceChildren(){this.children=[];this.value='';}
  querySelector(){return this.grid??=new Element();}
  getContext(){return ctx;}
}
const ids={};
for(const id of ['scale','ground','reduce','low','pause','step','showKeys','mood','time','base','overlay','lamp','roomScale','pose','playPose','room','roomStatus','weatherKeys','menu','palette','keys','sheets'])ids[id]=new Element();
for(const id of ['scale','ground','mood','time','base','overlay','roomScale','pose'])ids[id].kind='select';
Object.assign(ids.scale,{value:'6'});Object.assign(ids.ground,{value:'#F6F6F6'});
ids.mood.value='reading';ids.lamp.checked=true;ids.roomScale.value='3';
ids.time.value='day';ids.base.value='cloudy';ids.overlay.value='none';
class LocalImage {
  set src(url){assert(fs.existsSync(path.resolve(art,url)),`Missing sheet ${url}`);queueMicrotask(()=>this.onload());}
}
const sandbox={document:{getElementById:id=>ids[id],createElement:()=>new Element(),createTextNode:s=>({textContent:s})},performance:{now:()=>0},Image:LocalImage,requestAnimationFrame(){},window:{}};
vm.createContext(sandbox);
vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1],sandbox,{filename:'preview.html'});
await new Promise(ok=>setImmediate(ok));
assert(sandbox.window.previewReady,'Preview failed to initialise');
const states=['awake','reading','sleeping','digesting','happy','curious','hungry','error'];
const roomSheets=['backdrop','window','weather','skyfx','clock','plant','lamp','fly','beanbag','mug','spines'];
const expected=[...states.map(s=>'bookworm-'+s),...states.flatMap(s=>['dark','lit'].map(l=>`bookworm-${s}-night-${l}`)),'bookworm-small',...roomSheets.map(s=>'room-'+s)].sort();
assert.deepEqual(Array.from(vm.runInContext('Object.keys(D).sort()',sandbox)),expected);
assert.equal(vm.runInContext('tiles.length',sandbox),vm.runInContext('Object.values(D).reduce((n,d)=>n+d.meta.frameTags.length,0)',sandbox));
assert.equal(ids.sheets.children.length,expected.length);
assert.equal(ids.weatherKeys.children.length,15);
assert.equal(ids.menu.children.length,4);
assert.equal(ids.palette.children.length,vm.runInContext('DATA.palette.colors.length+Object.values(DATA.palette.night.ramps).flat().length+DATA.palette.scenery.colors.length+Object.values(DATA.palette.scenery.ramps).reduce((n,r)=>n+Object.keys(r).length,0)+Object.keys(DATA.palette.night.glyphs.question.colors).length+Object.keys(DATA.palette.clock.colors).length',sandbox));
const read=code=>vm.runInContext(code,sandbox);
let rooms=0;
for(const time of ['day','dusk','night'])for(const base of ['sunny','cloudy','windy','rainy','curtains'])
for(const mood of ['awake','reading','sleeping','digesting','happy','curious','hungry','error'])
 for(const lit of [false,true])for(const scale of ['3','4']){
  ids.time.value=time;ids.base.value=base;
  ids.mood.value=mood;ids.mood.onchange();ids.lamp.checked=lit;ids.roomScale.value=scale;
  for(const t of [0,2000,25000])read(`clock=${t};room()`);
  for(const prop of ['backdrop','window','plant','lamp','beanbag','mug']) {
    const expected=time==='night'||base==='rainy'?(lit?'night-lit':'night-dark'):['backdrop','lamp'].includes(prop)?(lit?'lit':'dark'):'idle';
    assert.equal(read(`roomTag('${prop}','${time}','${base}',${lit})`),expected);
  }
  assert.equal(read(`wormSheet('${mood}','${time}','${base}',${lit})`),`bookworm-${mood}`+(time==='night'||base==='rainy'?`-night-${lit?'lit':'dark'}`:''));
  for(const overlay of ['none','mist','celebration']) {
    const expected=overlay==='none'?null:overlay==='mist'?`mist-${time}`:time==='night'?'shootingstar-night':`rainbow-${time}`;
    assert.equal(read(`skyfxTag('${time}','${overlay}')`),expected);
    ids.overlay.value=overlay;read('room()');
  }
  assert.equal(ids.room.width,160*Number(scale));assert.equal(ids.room.height,64*Number(scale));rooms++;
 }
ids.weatherKeys.children[2].onclick();assert.equal(ids.time.value,'night');assert.equal(ids.base.value,'sunny');
read('room()');assert(ids.roomStatus.textContent.includes('Night'));
ids.mood.value='reading';ids.mood.onchange();ids.roomScale.value='3';
ids.low.checked=true;ids.reduce.checked=false;
const rainStart=read("tag('room-weather','rainy-night').from");
assert.equal(read("index('room-weather','rainy-night',100)"),rainStart);
assert.equal(read("index('room-weather','rainy-night',200)"),rainStart+1);
ids.reduce.checked=true;
assert.equal(read("index('room-weather','rainy-night',9000)"),rainStart);
read('room()');assert(ids.roomStatus.textContent.includes('Reading cover 1 / 3'));
ids.reduce.checked=false;ids.low.checked=false;
ids.pause.onclick();ids.step.onclick();
assert.equal(read("index('room-weather','rainy-night',9000)"),rainStart+1);
ids.pause.onclick();ids.pose.value='perk.center';ids.playPose.onclick();read('tick(10)');
assert.equal(ids.pause.textContent,'Pause');assert(draws>0);
console.log(`Offline script smoke check: ${expected.length} sheets, ${read('tiles.length')} tags, ${rooms} room combinations, all overlay choices, scenery thumbnails, Reduce Motion, Low Power, pause, step and pose controls OK (${draws} draw calls). Browser rendering remains unverified.`);
