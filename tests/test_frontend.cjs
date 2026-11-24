// Exercise the shipped async UI functions without a browser or network socket.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../static/app.js'), 'utf8');
function block(start, end) { return source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start))); }
function deferred() { let resolve; const promise = new Promise(r => resolve=r); return {promise,resolve}; }
const image = () => ({src:'',alt:'',removeAttribute(name){this[name]=''}});
const pending = new Map(), detail = deferred();
let page = 'collection';
const context = vm.createContext({
  WeakMap, mediaURL:path=>pending.get(path).promise, api:()=>detail.promise,
  document:{querySelectorAll:()=>[]}, localStorage:{removeItem(){}},
  clearPicks(){},clearMedia(){},showPage:value=>{page=value},
  $:()=>({}), URL:{revokeObjectURL(){}},
});
vm.runInContext(`let secret='test',sessionVersion=0,detailVersion=0,listVersion=0,current=null;`+
  block('const imageVersions=', 'function lock()')+
  block('function lock()', "$('lock').onclick")+
  block('async function openDetail(', 'function clearPreview()'),context);
(async()=>{
  const img=image(); pending.set('old',deferred());pending.set('new',deferred());
  const old=context.showImage(img,'old'), fresh=context.showImage(img,'new');
  pending.get('new').resolve('blob:new');await fresh;
  pending.get('old').resolve('blob:old');await old;
  assert.equal(img.src,'blob:new','old detail photo must not replace a newer photo');
  pending.set('preview',deferred());const preview=context.showImage(img,'preview');
  context.invalidateImage(img);img.src='blob:local-file';pending.get('preview').resolve('blob:remote');await preview;
  assert.equal(img.src,'blob:local-file','clearing or choosing a file must invalidate the old preview');
  pending.set('locked',deferred());const photo=context.showImage(img,'locked');
  const opening=context.openDetail('item');context.lock();
  detail.resolve({id:'item'});pending.get('locked').resolve('blob:locked');await opening;await photo;
  assert.equal(page,'gate','a late detail response must not reopen a locked wardrobe');
  assert.notEqual(img.src,'blob:locked','a late image must not be installed after locking');
  console.log('PASS frontend stale detail, stale image, local preview replacement and lock races');
})().catch(error=>{console.error(error);process.exitCode=1});

// Quantity controls must follow selections and the configured outfit target.
class El {
  constructor(tag='div',text=''){this.tag=tag;this.textContent=text;this.children=[];this.dataset={};this.hidden=false;this.disabled=false;this.value='';}
  append(...nodes){this.children.push(...nodes);if(this.tag==='select'&&!this.value&&nodes.length)this.value=String(nodes[0].value)}
  replaceChildren(...nodes){this.children=nodes}
  setAttribute(key,value){this[key]=value}
  querySelector(){return this.children.find(n=>n.tag==='select')}
  querySelectorAll(){return this.children.flatMap(n=>n.tag==='select'?[n]:n.querySelectorAll())}
  showModal(){this.open=true} close(){this.open=false}
}
const elements=new Map();const get=id=>{if(!elements.has(id))elements.set(id,new El());return elements.get(id)};
const buttons=['set','selected','other'].map(mode=>{const b=new El('button');b.dataset.draw=mode;return b});
let lastDraw;
const quantity=vm.createContext({
  $:get,element:(tag,text)=>new El(tag,text),Option:function(text,value){return {text,value}},
  document:{querySelectorAll:()=>buttons},selectItems:(path,body)=>{lastDraw=body},
});
vm.runInContext(`let drawing=false,selectedKinds=new Set(),owner='human',other='ai';
  const people={human:'我',ai:'伙伴'},categories={clothes:'衣服',toy:'玩具',extra:'额外格'};
  const rules={clothes:{max_count:1},toy:{max_count:3},extra:{max_count:2}};
  const outfitKinds=who=>who==='ai'?['clothes','extra']:['clothes','toy'];`+
  block('function updateDrawSelection(){','function renderOwner(){')+
  block('function countsFor(keys){','async function selectItems(')+
  block("document.querySelectorAll('[data-draw]')","$('pick-form').onsubmit"),quantity);
get('category-counts').append(...['clothes','toy','extra'].map(k=>quantity.countControl(k)));
quantity.updateDrawSelection();assert.equal(get('category-counts').hidden,true);
vm.runInContext("selectedKinds.add('toy')",quantity);quantity.updateDrawSelection();
assert.deepEqual(get('category-counts').children.filter(n=>!n.hidden).map(n=>n.querySelector().dataset.category),['toy']);
get('category-counts').children[1].querySelector().value='3';buttons[1].onclick();assert.equal(lastDraw.counts.toy,3);
vm.runInContext("selectedKinds.add('clothes')",quantity);quantity.updateDrawSelection();buttons[1].onclick();
assert.equal(Object.keys(lastDraw.counts).length,0);assert.equal(get('category-counts').children[1].querySelector().disabled,true);
buttons[0].onclick();assert.equal(get('outfit-dialog').open,true);
assert.deepEqual(get('outfit-counts').querySelectorAll().map(s=>s.dataset.category),['toy']);
get('outfit-counts').querySelectorAll()[0].value='3';get('outfit-form').onsubmit({preventDefault(){}});
assert.equal(lastDraw.target,'human');assert.equal(lastDraw.counts.toy,3);
buttons[2].onclick();assert.equal(get('outfit-title').textContent,'给伙伴抽一套');
assert.deepEqual(get('outfit-counts').querySelectorAll().map(s=>s.dataset.category),['extra']);
get('outfit-counts').querySelectorAll()[0].value='2';get('outfit-form').onsubmit({preventDefault(){}});
assert.equal(lastDraw.target,'ai');assert.equal(lastDraw.counts.extra,2);
vm.runInContext('selectedKinds.clear()',quantity);quantity.updateDrawSelection();assert.equal(get('category-counts').hidden,true);
console.log('PASS frontend default hidden, selected counts, fixed mixed draw, outfit counts, configured role and target-specific categories');
