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
for(const id of ['scale','ground','reduce','low','pause','step','showKeys','mood','lamp','roomScale','pose','playPose','room','roomStatus','weatherKeys','menu','palette','keys','sheets'])ids[id]=new Element();
for(const id of ['scale','ground','mood','roomScale','pose'])ids[id].kind='select';
Object.assign(ids.scale,{value:'6'});Object.assign(ids.ground,{value:'#F6F6F6'});
ids.mood.value='reading';ids.lamp.checked=true;ids.roomScale.value='3';
class LocalImage {
  set src(url){assert(fs.existsSync(path.resolve(art,url)),`Missing sheet ${url}`);queueMicrotask(()=>this.onload());}
}
const sandbox={document:{getElementById:id=>ids[id],createElement:()=>new Element(),createTextNode:s=>({textContent:s})},performance:{now:()=>0},Image:LocalImage,requestAnimationFrame(){},window:{}};
vm.createContext(sandbox);
vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1],sandbox,{filename:'preview.html'});
await new Promise(ok=>setImmediate(ok));
assert(sandbox.window.previewReady,'Preview failed to initialise');
assert.equal(vm.runInContext('tiles.length',sandbox),159);
assert.equal(ids.sheets.children.length,19);
assert.equal(ids.weatherKeys.children.length,7);
assert.equal(ids.menu.children.length,4);
assert.equal(ids.palette.children.length,82);
const read=code=>vm.runInContext(code,sandbox);
let rooms=0;
for(const mood of ['awake','reading','sleeping','digesting','happy','hungry','error'])
 for(const lit of [false,true])for(const scale of ['3','4']){
  ids.mood.value=mood;ids.mood.onchange();ids.lamp.checked=lit;ids.roomScale.value=scale;
  for(const t of [0,2000,25000])read(`clock=${t};room()`);
  assert.equal(ids.room.width,160*Number(scale));assert.equal(ids.room.height,64*Number(scale));rooms++;
 }
ids.mood.value='reading';ids.mood.onchange();ids.roomScale.value='3';
ids.low.checked=true;ids.reduce.checked=false;
assert.equal(read("index('room-weather','storm',80)"),204);
assert.equal(read("index('room-weather','storm',160)"),205);
ids.reduce.checked=true;
assert.equal(read("index('room-weather','storm',9000)"),204);
read('room()');assert(ids.roomStatus.textContent.includes('Reading cover 1 / 3'));
ids.reduce.checked=false;ids.low.checked=false;
ids.pause.onclick();ids.step.onclick();
assert.equal(read("index('room-weather','storm',9000)"),205);
ids.pause.onclick();ids.pose.value='perk.center';ids.playPose.onclick();read('tick(10)');
assert.equal(ids.pause.textContent,'Pause');assert(draws>0);
console.log(`Offline script smoke check: 19 sheets, 159 tags, ${rooms} room combinations, Reduce Motion, Low Power, pause, step and pose controls OK (${draws} draw calls). Browser rendering remains unverified.`);
