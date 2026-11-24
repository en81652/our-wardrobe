'use strict';
const $=id=>document.getElementById(id);
const readStorage=key=>{try{return localStorage.getItem(key)||''}catch{return ''}};
let config, categories={all:'全部'}, people={}, rules={}, actor='', other='', owner='';
const ownerKinds=who=>Object.keys(rules).filter(k=>rules[k].owners.includes(who));
const outfitKinds=who=>ownerKinds(who).filter(k=>rules[k].in_outfit===true||Array.isArray(rules[k].in_outfit)&&rules[k].in_outfit.includes(who));
const isOrder=item=>!!rules[item.category]?.text_only;
const actionText=(item,target)=>(people[target]||target)+(rules[item.category]?.action||'')+'：'+item.name;
let secret=readStorage('wardrobe_secret'), filter='all', selectedKinds=new Set(), pickedItems=new Map(), current=null, editing=null, previewURL='', drawing=false, saving=false, listVersion=0, sessionVersion=0, detailVersion=0;
const mediaCache=new Map();
function clearMedia(){for(const value of mediaCache.values())URL.revokeObjectURL(value);mediaCache.clear()}
async function mediaURL(path){
  const session=sessionVersion;
  const pathname=new URL(path,location.href).pathname;
  if(!/^\/api\/media\/[a-f0-9]{32}\.(jpg|png)$/.test(pathname))throw new Error('图片路径无效');
  if(mediaCache.has(pathname))return mediaCache.get(pathname);
  const response=await fetch(pathname,{headers:{Authorization:'Bearer '+secret},cache:'no-store'});
  if(!response.ok)throw new Error('图片暂时无法加载');
  const blob=await response.blob();if(session!==sessionVersion)throw new Error('衣柜已锁定');
  if(mediaCache.has(pathname))return mediaCache.get(pathname);
  const url=URL.createObjectURL(blob);mediaCache.set(pathname,url);return url;
}
const imageVersions=new WeakMap();
function invalidateImage(img){imageVersions.set(img,(imageVersions.get(img)||0)+1)}
async function showImage(img,path){invalidateImage(img);const version=imageVersions.get(img), session=sessionVersion;img.removeAttribute('src');try{const url=await mediaURL(path);if(version===imageVersions.get(img)&&session===sessionVersion)img.src=url}catch{if(version===imageVersions.get(img)&&session===sessionVersion)img.alt='图片暂时无法加载'}}
function lock(){secret='';sessionVersion++;detailVersion++;listVersion++;current=null;clearPicks();clearMedia();try{localStorage.removeItem('wardrobe_secret')}catch{};document.querySelectorAll('dialog[open]').forEach(d=>d.close());showPage('gate')}
$('lock').onclick=lock;
$('theme').value=readStorage('wardrobe_theme')||'harbor';
function setTheme(){document.documentElement.dataset.theme=$('theme').value;try{localStorage.setItem('wardrobe_theme',$('theme').value)}catch{}}
$('theme').onchange=setTheme;setTheme();
async function initialize(){
  const session=sessionVersion;
  try{
    config=await api('/api/config');if(session!==sessionVersion)return;categories={all:'全部'};rules={};people={};
    for(const c of config.categories){rules[c.id]=c;categories[c.id]=c.name}
    for(const r of config.roles)people[r.id]=r.name;
    actor=config.clients.web;other=config.clients.mcp;owner=actor;
    document.title=config.title+' · Wardrobe';$('page-title').textContent=config.title;
    $('owners').replaceChildren();$('owner').replaceChildren();
    for(const r of config.roles){const b=element('button',r.name+'的');b.dataset.owner=r.id;b.onclick=()=>{if(drawing)return;setOwner(r.id);$('status').textContent='';loadList()};$('owners').append(b);$('owner').append(new Option(r.name,r.id))}
    $('draw-other').textContent='给'+people[other]+'抽一套';renderOwner();await loadList();
  }catch(error){showPage('gate');$('gate-error').textContent=error.message}
}
function element(tag,text,className){const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(className)el.className=className;return el}
function showPage(id){for(const name of ['gate','collection','detail'])$(name).hidden=name!==id}
function dateText(value){return value?new Intl.DateTimeFormat('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).format(new Date(value)):''}
function errorText(detail){return typeof detail==='string'?detail:(detail&&detail.message)||'填写内容不符合要求，请检查字数和类别。'}
async function api(path,{method='GET',body,timeout=30000}={}){
  const controller=new AbortController(), timer=setTimeout(()=>controller.abort(),timeout);
  const headers={Authorization:'Bearer '+secret};
  if(body&&!(body instanceof FormData)){headers['Content-Type']='application/json';body=JSON.stringify(body)}
  try{
    const response=await fetch(path,{method,body,headers,signal:controller.signal,cache:'no-store'});
    if(response.status===401){lock();$('gate-error').textContent='密钥不正确或已失效，请重新输入。';throw new Error('请重新登录衣柜。')}
    const data=await response.json();
    if(!response.ok)throw new Error(errorText(data.detail));
    return data;
  }catch(error){if(error.name==='AbortError')throw new Error('请求超时，请先核对记录。');throw error}finally{clearTimeout(timer)}
}
function updateDrawSelection(){
  for(const button of $('draw-kinds').children)button.setAttribute('aria-pressed',String(selectedKinds.has(button.dataset.kind)));
  $('draw-selected').disabled=drawing||!selectedKinds.size;
  $('draw-selected').textContent=selectedKinds.size===1?'单抽这格':selectedKinds.size?`抽选中的 ${selectedKinds.size} 格`:'先选要抽的格子';
  $('category-counts').hidden=!selectedKinds.size;
  for(const label of $('category-counts').children){
    const select=label.querySelector('select');label.hidden=!selectedKinds.has(select.dataset.category);
    select.disabled=drawing||selectedKinds.size>1;
    if(selectedKinds.size>1)select.value='1';
  }
}
function renderOwner(){
  $('tabs').replaceChildren();$('draw-kinds').replaceChildren();$('category-counts').replaceChildren();
  for(const button of $('owners').children)button.setAttribute('aria-pressed',String(button.dataset.owner===owner));
  for(const key of ['all',...ownerKinds(owner)]){
    const button=element('button',categories[key]);button.dataset.kind=key;button.setAttribute('aria-pressed',String(key===filter));button.onclick=()=>{filter=key;loadList()};$('tabs').append(button);
    if(key!=='all'){
      const choice=element('button',categories[key]);choice.dataset.kind=key;choice.type='button';choice.onclick=()=>{if(drawing)return;selectedKinds.has(key)?selectedKinds.delete(key):selectedKinds.add(key);updateDrawSelection()};$('draw-kinds').append(choice);
      $('category-counts').append(countControl(key));
    }
  }
  $('draw-hint').textContent='给'+people[owner]+'抽一套：'+(outfitKinds(owner).map(k=>categories[k]).join('、')||'还没有设置套装格子')+'。其余格子可自选勾上。空格跳过。';
  updateDrawSelection();
}
function setOwner(who){clearPicks();owner=who;filter='all';selectedKinds=new Set();renderOwner()}
function updatePickSelection(){
  const count=pickedItems.size;
  $('pick-form').hidden=!count;$('add').hidden=!!count;
  $('collection').setAttribute('class',count?'has-picks':'');
  $('pick-summary').textContent=`给${people[owner]}挑 · 已选 ${count} 件：`+[...pickedItems.values()].join('、');
  for(const wrapper of $('grid').children){
    const checked=pickedItems.has(wrapper.dataset.id), checkbox=wrapper.children[1].children[0];
    checkbox.checked=checked;checkbox.disabled=drawing||!wrapper.dataset.enabled;
    wrapper.children[0].disabled=drawing;wrapper.setAttribute('data-picked',String(checked));
  }
  $('pick-submit').disabled=drawing||!count||count>8||[...$('pick-line').value].length>40;
  const previous=$('pool-count').value;$('pool-count').replaceChildren();for(let n=1;n<=Math.min(count,8);n++)$('pool-count').append(new Option(n+' 件',n));if(Number(previous)<=Math.min(count,8)&&previous)$('pool-count').value=previous;
  $('pool-submit').disabled=drawing||!count;$('pool-count').disabled=drawing;
  $('pick-clear').disabled=drawing;$('pick-line').disabled=drawing;
  $('pick-submit').textContent=drawing?'正在发送…':'挑这几件';
}
function clearPicks(){pickedItems.clear();$('pick-line').value='';$('pick-error').textContent='';updatePickSelection()}
$('pick-clear').onclick=()=>{if(!drawing)clearPicks()};
$('pick-line').oninput=()=>{$('pick-error').textContent=[...$('pick-line').value].length>40?'一句话最多 40 字。':'';updatePickSelection()};
function editorKinds(preferred=$('kind').value){
  $('kind').replaceChildren();for(const key of ownerKinds($('owner').value))$('kind').append(new Option(categories[key],key));
  $('kind').value=ownerKinds($('owner').value).includes(preferred)?preferred:(ownerKinds($('owner').value)[0]||'');updateNoteField();
}
function updateNoteField(){const order=!!rules[$('kind').value]?.text_only;$('note').required=order;$('note-label').textContent=order?'指令正文 · 必填':'短备注';$('note').maxLength=order?200:500;$('note-limit').textContent=order?'· 最多 200 字':'· 最多 500 字';$('note').placeholder=order?'写下要做的事，正文会直接显示在卡片上':'颜色、材质，或它的小故事';$('photo-field').hidden=order;if(order){$('image').value='';$('clear-image').checked=true;clearPreview()}}
$('owner').onchange=()=>editorKinds();$('kind').onchange=updateNoteField;
async function loadList(){
  const version=++listVersion;showPage('collection');$('loading').hidden=false;$('grid').replaceChildren();$('empty').hidden=true;$('retry').hidden=true;$('list-error').textContent='';$('count').textContent='';
  for(const button of $('tabs').children)button.setAttribute('aria-pressed',String(button.dataset.kind===filter));
  try{
    const {items}=await api('/api/items?owner='+encodeURIComponent(owner)+(filter==='all'?'':'&category='+encodeURIComponent(filter)));if(version!==listVersion)return;
    $('count').textContent=`${people[owner]}的 · ${categories[filter]} · ${items.length} 件`;
    for(const item of items){
      const card=element('button',undefined,'item');card.setAttribute('aria-label','查看'+item.name);
      const picture=element('span',undefined,'picture');
      if(item.image_url&&!isOrder(item)){const img=element('img');showImage(img,item.image_url);img.alt=item.name;img.loading='lazy';img.onerror=()=>picture.replaceChildren(element('span','照片暂时无法加载','placeholder'));picture.append(img)}
      else picture.append(element('span',isOrder(item)?item.description:item.name,isOrder(item)?'placeholder order-text':'placeholder'));
      card.append(picture,element('span',(categories[item.category]||'分类已停用'),'category'),element('strong',item.name),element('span',item.description||'还没有备注','item-note'),element('span',`用过 ${item.use_count} 次`,'count'));
      card.onclick=async()=>{if(drawing)return;card.disabled=true;try{await openDetail(item.id)}catch(e){$('list-error').textContent=e.message}finally{card.disabled=false}};
      const wrapper=element('div',undefined,'pick-item');wrapper.dataset.id=item.id;if(item.enabled)wrapper.dataset.enabled='true';
      const label=element('label',undefined,'pick-choice'), checkbox=element('input');checkbox.type='checkbox';checkbox.setAttribute('aria-label','挑选'+item.name);
      checkbox.onchange=()=>{if(!drawing){if(checkbox.checked)pickedItems.set(item.id,item.name);else if(!checkbox.checked)pickedItems.delete(item.id)}updatePickSelection()};
      label.append(checkbox,element('span','挑这件'));wrapper.append(card,label);$('grid').append(wrapper);
    }
    updatePickSelection();
    $('empty-title').textContent=filter==='all'?'衣柜还是空的':'这一格还是空的';$('empty').hidden=items.length>0;
  }catch(error){if(version===listVersion&&secret){$('list-error').textContent=error.message;$('retry').hidden=false}}
  finally{if(version===listVersion)$('loading').hidden=true}
}
function wardrobeLink(url){const link=element('a','打开衣柜');link.href=url;return link}
function renderHistory(rows,target){
  target.replaceChildren();if(!rows.length){target.append(element('p','还没有使用记录。','muted'));return}
  const delivery={disabled:'未接入',delivered:'已接收',failed:'接收失败',unknown:'结果未确认',pending:'等待确认',not_applicable:'无需通知'};
  for(const row of rows){const entry=element('div',undefined,'history-row');entry.append(element('p',`${dateText(row.created_at)} · ${row.chosen_by_name}${row.mode==='pick'?'挑选':'抽取'} · 给${row.target_name} · ${row.items.length} 件`));entry.append(element('p',`发卡片：${delivery[row.webhook?.status]||'未接入'} · 通知小机：${delivery[row.notification?.status]||'未接入'}`,'muted'));entry.append(element('p',row.text));const link=element('button','查看结果卡');link.onclick=async()=>{link.disabled=true;try{const session=sessionVersion, url=await mediaURL(row.card_url);if(session!==sessionVersion)return;invalidateImage($('zoom-image'));$('zoom-image').src=url;$('zoom-image').alt=row.text;$('zoom-dialog').showModal()}catch(e){entry.append(element('p',e.message,'error'))}finally{link.disabled=false}};entry.append(link);if(row.wardrobe_url)entry.append(wardrobeLink(row.wardrobe_url));target.append(entry)}
}
async function openDetail(id,focus=true){
  if(!secret||!id)return;
  const version=++detailVersion, session=sessionVersion;
  const item=await api('/api/items/'+encodeURIComponent(id));if(version!==detailVersion||session!==sessionVersion)return;current=item;showPage('detail');
  $('detail-name').textContent=item.name;$('detail-note').textContent=item.description||'还没有备注。';$('detail-meta').textContent=`${people[item.owner]||item.owner}用 · ${categories[item.category]||'分类已停用'} · ${people[item.added_by]||item.added_by}放进柜子`;
  $('detail-use').textContent=`用过 ${item.use_count} 次`+(item.last_used_at?` · 最近一次 ${dateText(item.last_used_at)}`:'');
  const showPhoto=item.image_url&&!isOrder(item);$('detail-placeholder').className=isOrder(item)?'placeholder order-text':'placeholder';
  $('detail-photo').hidden=!showPhoto;$('detail-placeholder').hidden=!!showPhoto;$('zoom-open').hidden=!item.image_url;
  if(showPhoto){showImage($('detail-photo'),item.image_url);$('detail-photo').alt=item.name}else{invalidateImage($('detail-photo'));$('detail-photo').removeAttribute('src');$('detail-placeholder').textContent=isOrder(item)?item.description:item.name}
  $('notes').replaceChildren();if(!item.notes.length)$('notes').append(element('p','背面还空着，留一句给它。','muted small'));
  for(const note of item.notes){const block=element('div',undefined,'note');block.append(element('p',note.text),element('small',`${note.author_name||people[note.author]||note.author} · ${dateText(note.created_at)}${note.updated_at?' · 修改于 '+dateText(note.updated_at):''}`));if(note.author===actor){const actions=element('div',undefined,'note-actions'), edit=element('button','修改批注'), remove=element('button','删除批注','danger');edit.onclick=()=>editNote(note);remove.onclick=()=>deleteNote(note);actions.append(edit,remove);block.append(actions)}$('notes').append(block)}
  renderHistory(item.uses,$('item-history'));$('remove-box').hidden=true;$('remove-error').textContent='';$('note-error').textContent='';
  if(focus){window.scrollTo(0,0);$('detail-name').focus({preventScroll:true})}
}
function clearPreview(){invalidateImage($('preview'));if(previewURL){URL.revokeObjectURL(previewURL);previewURL=''}$('preview').hidden=true;$('preview').removeAttribute('src')}
function openEditor(item=null){
  if(saving)return;
  editing=item;$('editor').reset();clearPreview();$('editor-error').textContent='';$('editor-title').textContent=item?'修改这件':'放进柜子';$('save').textContent=item?'保存修改':'放进去';
  $('name').value=item?.name||'';$('note').value=item?.description||'';$('owner').value=item?.owner||owner;editorKinds(item?.category||(filter==='all'?ownerKinds($('owner').value)[0]:filter));$('clear-image-label').hidden=!item?.image_url;
  if(item?.image_url){showImage($('preview'),item.image_url);$('preview').hidden=false}
  $('usage-fields').hidden=!item;$('use-count').value=item?.use_count||0;$('last-used').value=item?.last_used_at?new Date(new Date(item.last_used_at).getTime()-new Date(item.last_used_at).getTimezoneOffset()*60000).toISOString().slice(0,16):'';
  $('use-count').dataset.initial=$('use-count').value;$('last-used').dataset.initial=$('last-used').value;
  $('editor-dialog').showModal();
}
$('image').onchange=()=>{clearPreview();const file=$('image').files[0];if(file){previewURL=URL.createObjectURL(file);$('preview').src=previewURL;$('preview').hidden=false;$('clear-image').checked=false}};
$('clear-image').onchange=()=>{if($('clear-image').checked){$('image').value='';clearPreview()}};
$('editor-dialog').addEventListener('close',clearPreview);
$('editor-dialog').addEventListener('cancel',event=>{if(saving)event.preventDefault()});
document.querySelectorAll('[data-close]').forEach(button=>button.onclick=()=>{if(button.dataset.close==='editor-dialog'&&saving)return;$(button.dataset.close).close()});
$('editor').onsubmit=async event=>{
  event.preventDefault();if(saving)return;if(!$('name').value.trim()){$('editor-error').textContent='请填写名字。';return}
  if(rules[$('kind').value]?.text_only&&!$('note').value.trim()){$('editor-error').textContent='请填写指令正文。';return}
  const editId=editing?.id, session=sessionVersion;let saved=false;
  const data={name:$('name').value.trim(),category:$('kind').value,description:$('note').value.trim(),owner:$('owner').value};
  if(!editId)data.added_by=actor;
  if(editId){if($('use-count').value!==$('use-count').dataset.initial)data.use_count=Number($('use-count').value);if($('last-used').value!==$('last-used').dataset.initial)data.last_used_at=$('last-used').value?new Date($('last-used').value).toISOString():null}
  try{if($('image').files[0])data.image_base64=await fileBase64($('image').files[0]);else if(editId&&$('clear-image').checked)data.remove_image=true}catch(error){$('editor-error').textContent=error.message;return}
  saving=true;$('editor-dialog').querySelectorAll('button,input,textarea,select').forEach(el=>el.disabled=true);$('editor-error').textContent='';
  try{const item=await api('/api/items'+(editId?'/'+encodeURIComponent(editId):''),{method:editId?'PATCH':'POST',body:data,timeout:60000});saved=true;if(session!==sessionVersion)return;$('editor-dialog').close();if(editId){if(pickedItems.has(item.id)){if(item.owner===owner)pickedItems.set(item.id,item.name);else pickedItems.delete(item.id);updatePickSelection()}await openDetail(item.id,false)}else{setOwner(item.owner);await loadList();if(secret)$('status').textContent='已经放进柜子了。'}}
  catch(error){if(!secret)return;if(saved){$('status').textContent='已保存，刷新详情失败，请返回衣柜重新打开。';showPage('collection')}else{$('editor-error').textContent=error.message}}
  finally{saving=false;$('editor-dialog').querySelectorAll('button,input,textarea,select').forEach(el=>el.disabled=false)}
};
$('note-form').onsubmit=async event=>{event.preventDefault();const button=event.submitter;const text=$('note-text').value.trim();if(!text){$('note-error').textContent='先写一句吧。';return}button.disabled=true;try{await api('/api/items/'+current.id+'/notes',{method:'POST',body:{author:actor,text}});$('note-text').value='';await openDetail(current.id,false)}catch(error){$('note-error').textContent=error.message}finally{button.disabled=false}};

function fileBase64(file){if(file.size>5*1024*1024)throw new Error('图片不能超过 5 MB');return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=()=>reject(new Error('图片读取失败'));reader.readAsDataURL(file)})}
async function editNote(note){
  const dialog=$('note-editor');$('note-edit-text').value=note.text;$('note-edit-error').textContent='';dialog.showModal();
  $('note-edit-form').onsubmit=async event=>{event.preventDefault();const button=event.submitter;button.disabled=true;try{await api('/api/items/'+current.id+'/notes/'+note.id,{method:'PATCH',body:{author:actor,text:$('note-edit-text').value}});dialog.close();await openDetail(current.id,false)}catch(error){$('note-edit-error').textContent=error.message}finally{button.disabled=false}};
}
async function deleteNote(note){if(!confirm('确认删除这条批注？\n'+note.text))return;try{await api('/api/items/'+current.id+'/notes/'+note.id,{method:'DELETE',body:{author:actor,confirm:true}});await openDetail(current.id,false)}catch(error){$('note-error').textContent=error.message}}
function drawBusy(value){drawing=value;updatePickSelection();document.querySelectorAll('[data-draw],#owners button,#draw-kinds button,#category-counts select,#tabs button,#history-open').forEach(b=>b.disabled=value);updateDrawSelection()}
function countsFor(keys){const counts={};for(const select of $('category-counts').querySelectorAll('select'))if(keys.includes(select.dataset.category))counts[select.dataset.category]=Number(select.value);return counts}
async function selectItems(path,body,picking=false){
  if(drawing)return;const session=sessionVersion;drawBusy(true);$('status').textContent='正在给'+people[body.target]+'挑选…';$('pick-error').textContent='';
  try{const result=await api(path,{method:'POST',body:{...body,chosen_by:actor},timeout:65000});if(session!==sessionVersion)return;clearPicks();if(body.target!==owner)setOwner(body.target);await loadList();if(secret){$('status').replaceChildren(element('span','已经收好这次卡片 · '+result.items.map(i=>actionText(i,body.target)).join(' + ')));const view=element('button','查看这次卡片');view.onclick=async()=>{try{const session=sessionVersion, url=await mediaURL(result.card_url);if(session!==sessionVersion)return;invalidateImage($('zoom-image'));$('zoom-image').src=url;$('zoom-image').alt=result.text;$('zoom-dialog').showModal()}catch(e){$('status').append(element('p',e.message,'error'))}};$('status').append(view);if(result.wardrobe_url)$('status').append(wardrobeLink(result.wardrobe_url));if(['failed','unknown','pending'].includes(result.webhook.status)||['failed','unknown','pending'].includes(result.notification.status))$('status').append(element('p','投递未确认，请先查看抽取记录和接收端。'))}}
  catch(error){if(secret)$(picking?'pick-error':'status').textContent=error.message+'\n若请求超时，请先核对抽取记录，再决定是否重试。'}
  finally{drawBusy(false)}
}
document.querySelectorAll('[data-draw]').forEach(button=>button.onclick=()=>{
  const target=button.dataset.draw==='other'?other:owner, selected=button.dataset.draw==='selected';
  const keys=selected?[...selectedKinds]:outfitKinds(target);if(selected&&!keys.length)return;
  if(!selected){
    const adjustable=keys.filter(key=>rules[key].max_count>1);
    if(adjustable.length){
      $('outfit-title').textContent='给'+people[target]+'抽一套';$('outfit-form').dataset.target=target;
      $('outfit-counts').replaceChildren(...adjustable.map(countControl));$('outfit-dialog').showModal();return;
    }
  }
  const counts=selected&&keys.length===1?countsFor(keys):{};
  selectItems('/api/draw',{target,mode:'outfit',...(selected?{categories:keys}:{}),counts});
});
function countControl(key){
  const label=element('label',categories[key]), select=element('select');select.dataset.category=key;select.setAttribute('aria-label',categories[key]+'抽取数量');
  for(let n=1;n<=rules[key].max_count;n++)select.append(new Option(n+' 件',n));label.append(select);return label;
}
$('outfit-form').onsubmit=event=>{
  event.preventDefault();const counts={};for(const select of $('outfit-counts').querySelectorAll('select'))counts[select.dataset.category]=Number(select.value);
  const target=$('outfit-form').dataset.target;$('outfit-dialog').close();selectItems('/api/draw',{target,mode:'outfit',counts});
};
$('pick-form').onsubmit=event=>{event.preventDefault();if(pickedItems.size>8){$('pick-error').textContent='手挑最多八件；也可以从候选中抽几件。';return}selectItems('/api/pick',{target:owner,item_ids:[...pickedItems.keys()],line:$('pick-line').value},true)};
$('pool-submit').onclick=()=>selectItems('/api/draw',{target:owner,item_ids:[...pickedItems.keys()],count:Number($('pool-count').value),line:$('pick-line').value},true);
$('history-open').onclick=async()=>{$('history-list').textContent='正在读取…';$('history-dialog').showModal();try{const data=await api('/api/history?limit=20&target='+encodeURIComponent(owner));renderHistory(data.history,$('history-list'))}catch(error){$('history-list').textContent=error.message}};
$('remove-confirm').onclick=async()=>{$('remove-confirm').disabled=true;try{await api('/api/items/'+current.id,{method:'DELETE'});pickedItems.delete(current.id);updatePickSelection();current=null;await loadList();$('status').textContent='已经移出柜子，之前的记录还在。'}catch(error){$('remove-error').textContent=error.message}finally{$('remove-confirm').disabled=false}};
$('archive').onclick=()=>{$('remove-box').hidden=false;$('remove-confirm').focus()};$('remove-cancel').onclick=()=>{$('remove-box').hidden=true;$('archive').focus()};
$('back-list').onclick=()=>{detailVersion++;current=null;$('note-text').value='';loadList()};$('retry').onclick=loadList;$('edit').onclick=()=>openEditor(current);$('add').onclick=()=>openEditor();$('empty-add').onclick=()=>openEditor();
$('zoom-open').onclick=async()=>{$('zoom-image').alt=current.name;showImage($('zoom-image'),current.image_url);$('zoom-dialog').showModal()};
$('gate-form').onsubmit=async event=>{event.preventDefault();secret=$('secret').value.trim();if(!secret)return;try{localStorage.setItem('wardrobe_secret',secret)}catch{};$('secret').value='';await initialize()};
if(secret)initialize();else showPage('gate');
