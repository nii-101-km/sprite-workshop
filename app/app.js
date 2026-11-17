'use strict';
const $=s=>document.querySelector(s),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let state,category='all',page='collection',zoom=2,processed=false,selected=new Set(),visible=[],cards=new Map(),dirty=new Map(),seq=0,saving=false,saveTimer,polling=false,editing=null,formRevision=0,toastTimer;
let semanticResults=null,semanticQuery='',semanticStatus=null,semanticBusy=false,semanticRequest=0;
const draftKey='sprite-workshop-draft-v1';
const tr=(ru,en)=>{try{return localStorage.getItem('sprite-workshop-language')==='en'?en:ru;}catch(_){return ru;}};
const jobNames={queued:'Ожидает',running:'Выполняется',complete:'Завершено',failed:'Ошибка',unknown:'Нужна проверка',cancelled:'Отменено'};
async function api(path,body){const r=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await r.json();if(!r.ok){let e=new Error(window.WorkshopI18n?.translateError(window.WorkshopI18n.getLanguage(window.localStorage),data.error||'Не удалось выполнить действие')||data.error||'Не удалось выполнить действие');e.status=r.status;throw e;}return data;}
function uiText(text){return tr(text,window.WorkshopStaticTranslations?.[text]||window.WorkshopI18n?.translateError('en',text)||text);}
function toast(message,error=false){$('#toast').textContent=uiText(message);$('#toast').classList.toggle('error',error);$('#toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').hidden=true,error?10000:5000);}
function saveStatus(text,error=false){$('#save-status').textContent=uiText(text);$('#save-status').style.color=error?'#ffd490':'';}
function asset(key){return state.assets.find(a=>a.key===key);}
function draft(){try{localStorage.setItem(draftKey,JSON.stringify({root:state.root,edits:[...dirty].map(([key,v])=>({key,patch:v.patch,revision:v.revision,base:v.base,sourceSha:v.sourceSha}))}));}catch(e){saveStatus('Не удалось создать копию в браузере',true);}}
function syncDecision(change,current){
 if(current.job?.status==='running')return 'wait';
 if(change.patch.reviewed===true&&change.sourceSha&&change.sourceSha!==current.image?.source_sha256)return 'conflict';
 if(Object.entries(change.patch).every(([field,value])=>current[field]===value))return 'saved';
 if(change.revision===current.revision)return 'retry';
 if(!change.base)return 'conflict';
 return Object.entries(change.patch).every(([field,value])=>Object.prototype.hasOwnProperty.call(change.base,field)&&(current[field]===change.base[field]||current[field]===value))?'retry':'conflict';
}
function editInline(key,patch){
 const a=asset(key),old=dirty.get(key),full={...old?.patch,...patch};if('scale'in patch)full.reviewed=false;
 const base={...old?.base};for(const field of Object.keys(full))if(!(field in base))base[field]=a[field];
 Object.assign(a,full);dirty.set(key,{patch:full,base,sourceSha:old?.sourceSha??a.image?.source_sha256,revision:old?.revision??a.revision,seq:++seq,blocked:old?.blocked});
 draft();updateCard(a);counts();saveStatus('Сохраняем…');renderSaveIssues();clearTimeout(saveTimer);saveTimer=setTimeout(flush,400);
}
function renderSaveIssues(){
 const container=$('#notice');container.replaceChildren();
 const issues=[...dirty].filter(([,v])=>v.blocked||v.waiting||v.error);container.hidden=!issues.length;
 for(const [key,change] of issues){
  const row=document.createElement('div');row.className='save-issue';
  const text=document.createElement('p');text.textContent=`${asset(key)?.label||key}: ${change.blocked?tr('на диске есть другие изменения. Выберите, какие сохранить.','different changes exist on disk. Choose which version to keep.'):change.waiting?tr('сейчас обрабатывается. Правки сохранятся после завершения.','is being processed. Changes will be saved afterward.'):change.error}`;row.append(text);
  if(change.blocked){
   for(const [label,keepLocal] of [[tr('Сохранить мои правки','Keep my changes'),true],[tr('Оставить версию с диска','Keep disk version'),false]]){
    const button=document.createElement('button');button.textContent=label;button.onclick=()=>action(async()=>{
     button.disabled=true;try{
      const fresh=await api('/api/state'),current=fresh.assets.find(a=>a.key===key),pending=dirty.get(key);
      if(!current)throw new Error('Предмет не найден');if(!pending)return;
      if(keepLocal){pending.revision=current.revision;pending.base=Object.fromEntries(Object.keys(pending.patch).map(field=>[field,current[field]]));pending.sourceSha=current.image?.source_sha256;pending.blocked=false;pending.error=null;pending.waiting=false;pending.seq=++seq;}
      else {dirty.delete(key);Object.assign(asset(key),current);updateCard(asset(key));}
      draft();renderSaveIssues();await flush();
     }finally{button.disabled=false;}
    });row.append(button);
   }
  }
  container.append(row);
 }
}
async function flush(){
 if(saving||!dirty.size)return;saving=true;
 try{
  for(const key of [...dirty.keys()]){
   for(let attempt=0;attempt<3;attempt++){
    const pending=dirty.get(key);if(!pending||pending.blocked)break;
    const sent={...pending,patch:{...pending.patch},base:pending.base?{...pending.base}:undefined};
    try{
     const saved=await api('/api/asset',{key,patch:sent.patch,revision:sent.revision}),latest=dirty.get(key);
     if(latest?.seq===sent.seq){dirty.delete(key);Object.assign(asset(key),saved);}
     else if(latest){latest.revision=saved.revision;latest.base=Object.fromEntries(Object.keys(latest.patch).map(field=>[field,saved[field]]));latest.sourceSha=saved.image?.source_sha256;latest.waiting=false;latest.error=null;asset(key).revision=saved.revision;}
     updateCard(asset(key));break;
    }catch(e){
     const latest=dirty.get(key);if(!latest)break;
     if(e.status===409){
      try{
       const fresh=await api('/api/state'),current=fresh.assets.find(a=>a.key===key);if(!current)throw new Error('Предмет не найден');
       const decision=syncDecision(latest,current);
       if(decision==='saved'){dirty.delete(key);Object.assign(asset(key),current);updateCard(asset(key));break;}
       if(decision==='retry'){latest.revision=current.revision;latest.base=Object.fromEntries(Object.keys(latest.patch).map(field=>[field,current[field]]));latest.sourceSha=current.image?.source_sha256;latest.error=null;latest.waiting=false;continue;}
       latest.waiting=decision==='wait';latest.blocked=decision==='conflict';latest.error=null;
      }catch(error){latest.error=tr('Не удалось проверить сохранение: ','Could not verify the save: ')+uiText(error.message);}
     }else latest.error=tr('Не удалось сохранить: ','Could not save: ')+uiText(e.message);
     break;
    }
   }
  }
  draft();renderSaveIssues();
  if(!dirty.size)saveStatus('✓ Сохранено');else if([...dirty.values()].some(v=>v.blocked))saveStatus('Выберите версию правок',true);else if([...dirty.values()].some(v=>v.waiting))saveStatus('Сохраним после обработки');else saveStatus('Есть несохранённые правки',true);
 }finally{saving=false;if([...dirty.values()].some(v=>!v.blocked))saveTimer=setTimeout(flush,3000);}
}
async function settled(){
 clearTimeout(saveTimer);while(saving)await new Promise(r=>setTimeout(r,50));await flush();
 if(dirty.size){renderSaveIssues();if([...dirty.values()].some(v=>v.blocked))throw new Error('Есть разные версии правок. Выберите нужную в сообщении над коллекцией. Выгрузка настроек доступна.');throw new Error('Правки ещё сохраняются. После завершения обработки они сохранятся автоматически.');}
}
function exportProgress(data,edits){
 const result=JSON.parse(JSON.stringify(data));
 for(const edit of edits){const a=result.assets.find(a=>a.key===edit.key);if(a)Object.assign(a,edit.patch);}
 if(edits.length){result.draft=true;result.pending_edits=edits.map(e=>({key:e.key,patch:{...e.patch},revision:e.revision}));}
 return result;
}
async function refresh(force=false){if(polling)return;polling=true;try{const fresh=await api('/api/state');const changed=!state||JSON.stringify([fresh.categories,fresh.assets.map(a=>[a.key,a.revision,a.image?.source_sha256,a.output?.signature,a.job?.id,a.job?.status])])!==JSON.stringify([state.categories,state.assets.map(a=>[a.key,a.revision,a.image?.source_sha256,a.output?.signature,a.job?.id,a.job?.status])]);if(!state){state=fresh;render();return;}for(const a of fresh.assets){const old=asset(a.key);if(dirty.has(a.key)&&old)Object.assign(a,dirty.get(a.key).patch);}state=fresh;counts();renderQueue();if($('#directions-dialog').open)renderDirections();if(force||(changed&&!dirty.size&&!saving&&!document.activeElement?.matches('input,textarea,select')&&!document.querySelector('dialog[open]')))renderCollection();}catch(e){saveStatus('Нет связи с мастерской',true);if(force)toast(e.message,true);}finally{polling=false;}}
function counts(){
 const done=state.assets.filter(a=>a.available).length,ready=state.assets.filter(a=>a.output_current).length,pending=state.jobs.filter(j=>j.status==='queued').length;
 $('#progress').textContent=tr(`${done} исходников · ${ready} собрано · ${pending} в очереди`,`${done} sources · ${ready} built · ${pending} queued`);$('#queue-count').textContent=pending||'';$('#folder').textContent=state.root+'/output';
}
function nav(){
 const node=$('#groups');node.innerHTML='';for(const cat of ['all',...state.categories]){const button=document.createElement('button');button.className=category===cat?'active':'';const n=state.assets.filter(a=>!a.parent_key&&(cat==='all'||a.category===cat)).length;button.innerHTML=`${esc(cat==='all'?tr('Все предметы','All objects'):cat)}<span>${n}</span>`;button.onclick=()=>{category=cat;page='collection';render();};node.append(button);}
 $('#category-list').innerHTML=state.categories.map(c=>`<option value="${esc(c)}"></option>`).join('');
}
function render(){counts();nav();$('#collection').hidden=page!=='collection';$('#queue').hidden=page!=='queue';$('#collection-tab').classList.toggle('active',page==='collection');$('#queue-tab').classList.toggle('active',page==='queue');renderCollection();renderQueue();}
function updateCard(a){
 const card=cards.get(a.key);if(!card)return;const w=Math.max(1,Math.round(a.width*a.scale)),h=Math.max(1,Math.round(a.height*a.scale));const box=card.querySelector('.sprite-box');box.style.width=`${w*zoom}px`;box.style.height=`${h*zoom}px`;
 const range=card.querySelector('[type=range]'),number=card.querySelector('[type=number]');if(document.activeElement!==range)range.value=a.scale;if(document.activeElement!==number)number.value=a.scale.toFixed(2);
 card.querySelector('.dimensions').textContent=`${w} × ${h} px`;card.querySelector('.review input').checked=a.reviewed;card.classList.toggle('reviewed',a.reviewed);
 card.querySelector('.select-asset').checked=selected.has(a.key);
}
const actionIcons={trash:'<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/>',settings:'<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3"/><circle cx="15" cy="17" r="3"/>',pixels:'<path d="M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3z"/><path d="M14 14h3v3h-3zM18 18h3v3h-3z"/>',views:'<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',cube:'<path d="m12 2 9 5v10l-9 5-9-5V7zM3 7l9 5 9-5M12 12v10M7 4.8l9 5"/>',refresh:'<path d="M20 8a8 8 0 1 0 0 8M20 3v5h-5"/>',download:'<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',upload:'<path d="M12 16V4m-5 5 5-5 5 5M4 16v5h16v-5"/>',mirror:'<path d="M12 3v18M3 8l5 4-5 4zM21 8l-5 4 5 4z"/>'};
function actionIcon(name){return `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${actionIcons[name]}</svg>`;}
function iconAttrs(label){label=uiText(label);return `class="icon-action" title="${esc(label)}" aria-label="${esc(label)}"`;}
function localizeCard(card,a){
 const warning=a.available&&!a.image.alpha_ok;
 const status=({queued:'Queued',running:'Running',complete:'Completed',failed:'Failed',unknown:'Needs review',cancelled:'Cancelled'})[a.job?.status]||a.job?.status;
 const tag=a.job?tr(jobNames[a.job.status],status)+' · '+(a.job.kind==='generate'?tr('генерация','generation'):tr('сборка','build')):warning?tr('ПРОВЕРИТЬ АЛЬФУ','CHECK TRANSPARENCY'):processed?(a.output_current?tr('ГОТОВЫЙ PNG','FINISHED PNG'):a.output?tr('УСТАРЕВШАЯ СБОРКА','OUTDATED BUILD'):tr('ЕЩЁ НЕ СОБРАН','NOT BUILT')):(a.mode==='tile'?tr('ТАЙЛ · ПОЛНЫЙ КАДР','TILE · FULL FRAME'):tr('ИСХОДНИК · БЕЗ ПОЛЕЙ','SOURCE · TRIMMED'));
 card.querySelector('.stage-tag').textContent=tag;
 const placeholder=card.querySelector('.placeholder');if(placeholder)placeholder.textContent=processed?tr('Нажмите «Собрать PNG»','Click Build PNG'):tr('Добавлено в очередь','Added to queue');
 card.querySelector('.select-asset').setAttribute('aria-label',tr('Выбрать: ','Select: ')+a.label);
 const reset=card.querySelector('.reset');reset.title=tr('Исходный масштаб','Original scale');reset.setAttribute('aria-label',tr('Сбросить масштаб: ','Reset scale: ')+a.label);
 card.querySelector('.scale-row span').textContent=tr('Масштаб предмета','Object scale');
 card.querySelector('[type=number]').setAttribute('aria-label',tr('Масштаб: ','Scale: ')+a.label);
 card.querySelector('[type=range]').setAttribute('aria-label',tr('Изменить масштаб: ','Change scale: ')+a.label);
 const review=card.querySelector('.review');review.lastChild.textContent=tr('Размер принят','Size approved');
 for(const [selector,ru,en] of [['.edit','Настройки','Settings'],['.pixelize','Пикселизировать','Pixelate'],['.directions','Ракурсы · 4','Views · 4'],['.regenerate','Перегенерировать','Regenerate'],['a[download]','Скачать PNG','Download PNG']]){const el=card.querySelector(selector);if(el){el.title=tr(ru,en);el.setAttribute('aria-label',tr(ru,en));}}
 const orient=card.querySelector('.orient-shortcut');if(orient){orient.title=tr('Поворот, наклон и высота модели','Model rotation, tilt, and height');orient.setAttribute('aria-label',tr('Настроить 3D: ','Adjust 3D: ')+a.label);}
 const remove=card.querySelector('.delete-asset');remove.title=tr('Убрать в корзину','Move to trash');remove.setAttribute('aria-label',tr('Убрать в корзину: ','Move to trash: ')+a.label);
 const history=card.querySelector('.history');if(history)history.textContent=tr(`Архив исходников: ${a.history_count} ↗`,`Source history: ${a.history_count} ↗`);
 const notes=card.querySelectorAll('.tile-note');let index=0;if(warning)notes[index++].textContent=tr('Альфа не соответствует режиму. Исходник сохранён; сборка заблокирована.','Transparency does not match the mode. The source is saved; building is blocked.');if(a.output&&!a.output_current)notes[index].textContent=tr('Размер или исходник изменился. Соберите PNG заново.','The size or source changed. Rebuild the PNG.');
}
function makeCard(a){
 const card=document.createElement('article');card.className='card';card.dataset.key=a.key;
 const warning=a.available&&!a.image.alpha_ok;const output=processed&&a.output;const tag=a.job?(jobNames[a.job.status]+' · '+(a.job.kind==='generate'?'генерация':'сборка')):warning?'ПРОВЕРИТЬ АЛЬФУ':processed?(a.output_current?'ГОТОВЫЙ PNG':a.output?'УСТАРЕВШАЯ СБОРКА':'ЕЩЁ НЕ СОБРАН'):(a.mode==='tile'?'ТАЙЛ · ПОЛНЫЙ КАДР':'ИСХОДНИК · БЕЗ ПОЛЕЙ');
 const show=processed?!!a.output:a.available;
 card.innerHTML=`<div class="stage"><span class="stage-tag ${warning?'warning':''}">${esc(tag)}</span><input class="select-asset" type="checkbox" aria-label="Выбрать: ${esc(a.label)}"><div class="scene"><div class="ruler" aria-hidden="true"><span>64 px</span></div><div class="sprite-box">${show?`<img loading="lazy" src="/thumb?key=${encodeURIComponent(a.key)}${output?'&processed=1':''}&v=${a.revision}" alt="${esc(a.label)}">`:''}</div></div>${show?'':`<div class="placeholder">${processed?'Нажмите «Собрать PNG»':'Добавлено в очередь'}</div>`}</div><div class="details"><div class="name-row"><div><h3>${esc(a.label)}</h3><div class="asset-id">${esc(a.id)}${semanticResults?.some(r=>r.key===a.key)?' · сходство '+semanticResults.find(r=>r.key===a.key).score.toFixed(3):''}</div></div><button class="reset" title="Исходный масштаб" aria-label="Сбросить масштаб: ${esc(a.label)}">↺</button></div><div class="scale-row"><span>Масштаб предмета</span><label class="number-wrap">× <input type="number" min="0.1" max="4" step="0.01" aria-label="Масштаб: ${esc(a.label)}"></label></div><input type="range" min="0.1" max="4" step="0.01" aria-label="Изменить масштаб: ${esc(a.label)}"><div class="card-bottom"><span class="dimensions"></span><label class="review"><input type="checkbox" ${!a.available||a.job?.status==='running'?'disabled':''}>Размер принят</label></div><div class="card-actions"><button class="edit icon-action" title="Настройки" aria-label="Настройки">${actionIcon('settings')}</button>${a.available?`<button class="pixelize icon-action" title="Пикселизировать" aria-label="Пикселизировать">${actionIcon('pixels')}</button>`:''}${a.mode==='prop'?`<button class="directions icon-action" title="Ракурсы · 4" aria-label="Ракурсы · 4">${actionIcon('views')}</button>`:''}${a.mode==='prop'&&!a.parent_key?`<button class="orient-shortcut icon-action" title="Поворот, наклон и высота модели" aria-label="Настроить 3D: ${esc(a.label)}">${actionIcon('cube')}</button>`:''}<button class="regenerate icon-action" title="Перегенерировать" aria-label="Перегенерировать">${actionIcon('refresh')}</button>${a.output?`<a class="icon-action" title="Скачать PNG" aria-label="Скачать PNG" href="/png?key=${encodeURIComponent(a.key)}" download="${esc(a.id)}.png">${actionIcon('download')}</a>`:''}<button class="delete-asset icon-action" title="Убрать в корзину" aria-label="Убрать в корзину: ${esc(a.label)}">${actionIcon('trash')}</button></div>${a.history_count?`<a class="small-link history">Архив исходников: ${a.history_count} ↗</a>`:''}${warning?'<p class="tile-note">Альфа не соответствует режиму. Исходник сохранён; сборка заблокирована.</p>':''}${a.output&&!a.output_current?'<p class="tile-note">Размер или исходник изменился. Соберите PNG заново.</p>':''}</div>`;
 localizeCard(card,a);
 card.querySelector('.delete-asset').onclick=()=>action(async()=>{await settled();const current=asset(a.key),result=await api('/api/trash/remove',{key:a.key,revision:current.revision});for(const key of result.keys)selected.delete(key);semanticResults=null;await refresh(true);toast(tr('Убрано в корзину. Можно восстановить через кнопку «Корзина».','Moved to trash. You can restore it from Trash.'));});
 if(card.querySelector('.pixelize'))card.querySelector('.pixelize').onclick=()=>action(async()=>{await settled();await api('/api/enqueue',{keys:[a.key],kind:'process'});await api('/api/start',{});toast('Пикселизация запущена');await refresh(true);});
 if(card.querySelector('.orient-shortcut'))card.querySelector('.orient-shortcut').onclick=()=>document.dispatchEvent(new CustomEvent('open-model-orientation',{detail:{key:a.key}}));
 if(card.querySelector('.directions'))card.querySelector('.directions').onclick=()=>action(()=>openDirections(a.key));
 cards.set(a.key,card);for(const e of card.querySelectorAll('[type=range],[type=number]'))e.oninput=()=>{const n=Number(e.value);if(Number.isFinite(n)&&n>=.1&&n<=4)editInline(a.key,{scale:Math.round(n*100)/100});};
 card.querySelector('[type=number]').onchange=e=>{if(!e.target.value||+e.target.value<.1||+e.target.value>4)e.target.value=asset(a.key).scale;};
 card.querySelector('.reset').onclick=()=>editInline(a.key,{scale:1});card.querySelector('.review input').onchange=e=>editInline(a.key,{reviewed:e.target.checked});
 card.querySelector('.select-asset').onchange=e=>{if(e.target.checked)selected.add(a.key);else selected.delete(a.key);selection();};
 card.querySelector('.edit').onclick=()=>openAsset(a.key,false);card.querySelector('.regenerate').onclick=()=>openAsset(a.key,true);
 if(a.history_count)card.querySelector('.history').onclick=()=>openHistory(a.key);
 updateCard(a);return card;
}
function selection(){const n=selected.size;$('#selection-info').textContent=n?tr(`Выбрано ${n} предметов. Сборка применится к выбранным, включая другие разделы.`,`${n} objects selected, including any in other sections.`):tr('Без выбора собираются подходящие предметы текущего раздела.','Without a selection, eligible objects in this section will be built.');$('#build').textContent=n?tr(`Собрать выбранные (${n})`,`Build selected (${n})`):tr('Собрать подходящие PNG','Build eligible PNGs');$('#select-all').checked=visible.length>0&&visible.every(a=>selected.has(a.key));}
function renderCollection(){
 nav();$('#section-title').textContent=category==='all'?tr('Все предметы','All objects'):category;const q=$('#search').value.toLocaleLowerCase('ru').trim(),filter=$('#filter').value;
 visible=state.assets.filter(a=>!a.parent_key&&(category==='all'||a.category===category)&&(!semanticResults||semanticResults.some(r=>r.key===a.key))&&(!q||`${a.label} ${a.id}`.toLocaleLowerCase('ru').includes(q))&&(filter==='all'||filter==='reviewed'&&a.reviewed||filter==='unreviewed'&&!a.reviewed||filter==='alpha'&&a.available&&!a.image.alpha_ok||filter==='ready'&&a.output_current||filter==='missing'&&!a.available));
 if(semanticResults){const order=new Map(semanticResults.map((r,i)=>[r.key,i]));visible.sort((a,b)=>order.get(a.key)-order.get(b.key));}
 cards.clear();$('#grid').replaceChildren(...visible.map(makeCard));$('#empty').hidden=visible.length>0;$('#section-count').textContent=tr(`${visible.length} ПРЕДМЕТОВ · ${processed?'ГОТОВЫЕ PNG':'ИСХОДНИКИ'}`,`${visible.length} OBJECTS · ${processed?'FINISHED PNGS':'SOURCES'}`);selection();
 $('#raw-mode').classList.toggle('active',!processed);$('#output-mode').classList.toggle('active',processed);
}
function renderQueue(){
 if(!state)return;const jobs=[...state.jobs].reverse();const queued=jobs.filter(j=>j.status==='queued').length;$('#queue-status').textContent=state.running?(state.paused?tr('Пауза после текущего задания','Pausing after current job'):tr('Выполняется одно задание','One job is running')):tr(`Ожидает запуска: ${queued}`,`Waiting to start: ${queued}`);
 $('#jobs').innerHTML=jobs.length?'':tr('<div class="empty-state">Очередь пуста. Добавьте один промпт или целый пакет.</div>','<div class="empty-state">The queue is empty. Add a prompt or a batch.</div>');
 for(const j of jobs){const a=asset(j.key),row=document.createElement('article');row.className='job status-'+j.status;row.innerHTML=`<div><strong>${esc(a?.label||j.key)}</strong> <span class="chip">${j.kind==='generate'?tr('Генерация','Generation'):tr('Сборка PNG','PNG build')}</span><p>${esc(tr(jobNames[j.status]||j.status,({queued:'Queued',running:'Running',complete:'Completed',failed:'Failed',unknown:'Needs review',cancelled:'Cancelled'})[j.status]||j.status))} · <code>${esc(j.key)}</code></p>${j.error?`<p class="error">${esc(uiText(j.error))}</p>`:''}${j.processing_error?`<p class="error">${esc(uiText(j.processing_error))}</p>`:''}</div>${j.status==='queued'?tr('<button class="cancel">Убрать из очереди</button>','<button class="cancel">Remove from queue</button>'):j.status==='unknown'?tr('<button class="recover">Проверить результат</button>','<button class="recover">Check result</button>'):''}`;
  if(j.status==='queued')row.querySelector('.cancel').onclick=()=>action(async()=>{await api('/api/cancel',{id:j.id});await refresh(true);});
  if(j.status==='unknown')row.querySelector('.recover').onclick=()=>action(async()=>{const result=await api('/api/recover',{id:j.id});toast(result.status==='complete'?tr('Результат найден. Повтор не отправлялся.','Result found. No retry was sent.'):tr('Проверка завершена. Посмотрите состояние задания.','Check complete. See the job status.'));await refresh(true);});
  $('#jobs').append(row);
 }
}
async function action(fn){try{await fn();}catch(e){toast(e.message,true);}}
$('#collection-tab').onclick=$('#back-collection').onclick=()=>{page='collection';render();};$('#queue-tab').onclick=$('#queue-open').onclick=()=>{page='queue';render();};
$('#start').onclick=()=>action(async()=>{await settled();await api('/api/start',{});toast(tr('Очередь запущена','Queue started'));await refresh(true);});
$('#pause').onclick=()=>action(async()=>{await api('/api/pause',{});toast(tr('Текущее задание завершится. Следующие останутся в очереди.','The current job will finish. Remaining jobs stay queued.'));await refresh(true);});
$('#select-all').onchange=e=>{for(const a of visible){if(e.target.checked)selected.add(a.key);else selected.delete(a.key);updateCard(a);}selection();};
$('#search').oninput=()=>{semanticResults=null;semanticQuery='';renderCollection();};$('#filter').onchange=renderCollection;$('#zoom').onchange=e=>{zoom=+e.target.value;document.documentElement.style.setProperty('--zoom',zoom);for(const a of state.assets)updateCard(a);};
$('#raw-mode').onclick=()=>{processed=false;renderCollection();};$('#output-mode').onclick=()=>{processed=true;renderCollection();};
$('#build').onclick=()=>action(async()=>{
 await settled();let candidates=selected.size?state.assets.filter(a=>selected.has(a.key)):visible;
 const usable=candidates.filter(a=>a.available&&a.image.alpha_ok&&!a.job);const skipped=candidates.length-usable.length;
 if(!usable.length)throw new Error('Нет подходящих исходников. Проверьте альфу и задания в очереди.');
 await api('/api/enqueue',{kind:'process',keys:usable.map(a=>a.key)});await api('/api/start',{});toast(tr(`Сборка запущена: ${usable.length}.${skipped?' Пропущено без исходника, с неверной альфой или заданием: '+skipped+'.':''}`,`Build started: ${usable.length}.${skipped?' Skipped missing sources, invalid transparency, or active jobs: '+skipped+'.':''}`));page='queue';await refresh(true);render();
});
for(const b of document.querySelectorAll('[data-close]'))b.onclick=()=>$('#'+b.dataset.close).close();
function fillForm(form,d){for(const [k,v] of Object.entries(d)){const input=form.elements.namedItem(k);if(input){if(input.type==='checkbox')input.checked=v;else input.value=v;}}}
function formData(form){const get=n=>form.elements.namedItem(n);return {id:get('id').value.trim(),label:get('label').value.trim(),category:get('category').value.trim(),prompt:get('prompt').value.trim(),perspective:get('perspective').value,direction:get('direction').value,style:get('style').value.trim(),mode:get('mode').value,width:+get('width').value,height:+get('height').value,palette:+get('palette').value,seed:+get('seed').value,scale:+get('scale').value,auto_process:get('auto_process').checked,reference:get('reference').value||null};}
async function openAsset(key=null,regen=false){
 try{await settled();}catch(e){toast(e.message,true);return;}
 editing=key;const form=$('#asset-form');form.reset();$('#asset-error').textContent='';let d=key?{...asset(key),seed:regen?Math.floor(Math.random()*2**32):asset(key).seed}:{category:category==='all'?'Общее':category,style:state.style,width:32,height:32,palette:32,seed:Math.floor(Math.random()*2**32),scale:1,auto_process:true,mode:'prop',perspective:'rpg',direction:'front'};formRevision=d.revision;fillForm(form,d);$('#reference-file').value='';showReference(d.reference||null);$('#reference-current').hidden=!d.available;form.elements.prompt.required=!key;form.elements.id.disabled=!!key;form.elements.category.disabled=!!key;$('#asset-heading').textContent=key?(regen?tr('Перегенерировать предмет','Regenerate object'):tr('Настройки предмета','Object settings')):tr('Новый предмет','New object');$('#submit-asset').textContent=key?tr('Перегенерировать','Regenerate'):tr('Добавить в очередь','Add to queue');$('#save-edit').hidden=!key;$('#asset-dialog').showModal();
}
let referenceBusy=false;
function showReference(id){const form=$('#asset-form');form.elements.reference.value=id||'';$('#reference-preview').hidden=!id;if(id)$('#reference-preview').src='/reference?id='+encodeURIComponent(id);else $('#reference-preview').removeAttribute('src');$('#reference-remove').hidden=!id;}
async function uploadReference(file){
 if(referenceBusy)return;referenceBusy=true;$('#submit-asset').disabled=true;$('#save-edit').disabled=true;$('#asset-error').textContent='';
 try{if(!file||file.size>8_000_000)throw new Error('Выберите изображение до 8 МБ');const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=()=>reject(new Error('Не удалось прочитать файл'));reader.readAsDataURL(file);});const result=await api('/api/reference',{data});showReference(result.reference);}
 catch(e){$('#asset-error').textContent=uiText(e.message);}
 finally{referenceBusy=false;$('#submit-asset').disabled=false;$('#save-edit').disabled=false;}
}
$('#reference-file').onchange=e=>uploadReference(e.target.files[0]);
$('#reference-remove').onclick=()=>{showReference(null);$('#reference-file').value='';};
$('#reference-current').onclick=async()=>{try{const response=await fetch('/raw?key='+encodeURIComponent(editing));if(!response.ok)throw new Error('Не удалось загрузить исходник');await uploadReference(await response.blob());}catch(e){$('#asset-error').textContent=uiText(e.message);}};
$('#new-open').onclick=()=>openAsset();
async function saveForm(){
 if(referenceBusy)throw new Error('Дождитесь загрузки референса');
 if(!$('#asset-form').reportValidity())return null;
 const data=formData($('#asset-form'));
 if(editing){await settled();const d=await api('/api/asset',{key:editing,patch:data,revision:formRevision});formRevision=d.revision;Object.assign(asset(editing),d);return d.key;}
 const result=await api('/api/add',{assets:[data]});return result.keys[0];
}
$('#asset-form').onsubmit=async e=>{
 e.preventDefault();$('#submit-asset').disabled=true;$('#asset-error').textContent='';
 try{const key=await saveForm();if(!key)return;if(editing){await api('/api/enqueue',{kind:'generate',keys:[key]});await api('/api/start',{});toast('Перегенерация запущена. Прежний исходник сохранится в архиве.');}else toast('Предмет добавлен. Нажмите «Запустить очередь», когда будете готовы.');$('#asset-dialog').close();page='queue';await refresh(true);render();}catch(error){$('#asset-error').textContent=uiText(error.message);}finally{$('#submit-asset').disabled=false;}
};
$('#save-edit').onclick=async()=>{try{await saveForm();$('#asset-dialog').close();await refresh(true);toast('Настройки сохранены');}catch(e){$('#asset-error').textContent=uiText(e.message);}};
let batchStamp=Date.now();
function batchItems(){
 const form=$('#batch-form'),text=$('#batch-text').value.trim(),f=n=>form.elements.namedItem(n);
 if(!text)return [];
 const defaults={category:f('category').value,mode:f('mode').value,perspective:f('perspective').value,direction:f('direction').value,width:+f('width').value,height:+f('height').value,palette:+f('palette').value,auto_process:f('auto_process').checked,style:state.style,scale:1};
 let items;
 if(text.startsWith('{')||text.startsWith('[')){const data=JSON.parse(text);items=Array.isArray(data)?data:data.assets;if(!Array.isArray(items))throw new Error('В JSON нужен массив assets.');}
 else items=text.split(/\r?\n/).map(s=>s.trim()).filter(Boolean).map((prompt,i)=>({id:`item_${batchStamp}_${i+1}`,label:prompt.slice(0,60),prompt,seed:i+42}));
 if(items.length>500)throw new Error('За один раз можно добавить до 500 заданий.');
 return items.map((item,i)=>{if(!item||typeof item!=='object'||Array.isArray(item))throw new Error(tr('Задание '+(i+1)+' должно быть объектом.','Job '+(i+1)+' must be an object.'));return {...defaults,seed:42+i,...item};});
}
function batchPreview(){try{const items=batchItems();$('#batch-preview').textContent=items.length?tr(`${items.length} заданий\n`,`${items.length} jobs\n`)+items.slice(0,8).map(a=>`${a.category} / ${a.id} · ${a.width}×${a.height} · ${a.label||a.id}`).join('\n')+(items.length>8?'\n…':''):uiText('Добавьте задания для предпросмотра.');$('#batch-preview').style.whiteSpace='pre-wrap';$('#batch-error').textContent='';}catch(e){$('#batch-error').textContent=uiText(e.message);}}
$('#batch-open').onclick=()=>{$('#batch-form').reset();$('#batch-text').value='';$('#batch-form').elements.category.value=category==='all'?'Общее':category;batchStamp=Date.now();batchPreview();$('#batch-dialog').showModal();};
$('#batch-form').oninput=batchPreview;$('#pick-batch').onclick=()=>$('#batch-file').click();
$('#batch-file').onchange=async e=>{try{const file=e.target.files[0];if(!file)return;if(file.size>3_000_000)throw new Error('Файл слишком большой.');$('#batch-text').value=await file.text();batchStamp=Date.now();batchPreview();}catch(error){$('#batch-error').textContent=uiText(error.message);}finally{e.target.value='';}};
$('#batch-form').onsubmit=async e=>{e.preventDefault();$('#submit-batch').disabled=true;try{const items=batchItems();await api('/api/add',{assets:items});$('#batch-dialog').close();toast(tr(`В очередь добавлено ${items.length} заданий. Генерация ещё не запущена.`,`${items.length} jobs added to the queue. Generation has not started.`));page='queue';await refresh(true);render();}catch(error){$('#batch-error').textContent=uiText(error.message);}finally{$('#submit-batch').disabled=false;}};
$('#new-category').onclick=()=>{$('#category-form').reset();$('#category-error').textContent='';$('#category-dialog').showModal();};
$('#category-form').onsubmit=async e=>{e.preventDefault();try{const r=await api('/api/category',{name:$('#category-form').elements.category.value});category=r.category;page='collection';$('#category-dialog').close();await refresh(true);render();}catch(error){$('#category-error').textContent=uiText(error.message);}};
$('#export-settings').onclick=()=>action(async()=>{
 // Export never depends on the save gate, including conflicts and restored drafts.
 let data;try{data=await api('/api/settings');}catch(e){data={application:'sprite-workshop',version:1,assets:state.assets.map(a=>({...a}))};}
 const edits=new Map();try{const stored=JSON.parse(localStorage.getItem(draftKey)||'null');if(stored?.root===state.root)for(const e of stored.edits||[])edits.set(e.key,e);}catch(e){}
 for(const [key,v] of dirty)edits.set(key,{key,...v});
 data=exportProgress(data,[...edits.values()]);
 const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)+'\n'],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download=data.draft?'sprite-workshop-settings-draft.json':'sprite-workshop-settings.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),2000);
 toast(data.draft?'Резервная копия выгружена вместе с несохранёнными правками.':'Настройки выгружены. Исходники остаются в папке raw.');
});
$('#import-settings').onclick=()=>$('#settings-file').click();$('#settings-file').onchange=async e=>{try{const file=e.target.files[0];if(!file)return;if(file.size>3_000_000)throw new Error('Слишком большой JSON');await settled();const data=JSON.parse(await file.text());const r=await api('/api/import-settings',data);toast(tr(`Загружены настройки ${r.imported} предметов`,`Settings loaded for ${r.imported} objects`));await refresh(true);}catch(error){toast(error.message,true);}finally{e.target.value='';}};
async function openHistory(key){try{const rows=await api('/api/history?key='+encodeURIComponent(key));$('#history-content').innerHTML=rows.length?rows.map(row=>`<div class="history-row"><a href="/history?key=${encodeURIComponent(key)}&version=${encodeURIComponent(row.version)}" target="_blank">${tr("Исходник","Source")} ${esc(row.version)} ↗</a><p>${tr("Масштаб","Scale")}: ×${esc(row.scale)} · ${esc(row.width)} × ${esc(row.height)} px</p></div>`).join(''):uiText('Предыдущих исходников пока нет.');$('#history-dialog').showModal();}catch(e){toast(e.message,true);}}

async function refreshSemanticStatus(){
 try{
  semanticStatus=await api('/api/semantic/status');const s=semanticStatus;
  $('#semantic-status').textContent=s.running?tr(`Индексируем ${s.done} / ${s.total}${s.current?' · '+s.current:''}`,`Indexing ${s.done} / ${s.total}${s.current?' · '+s.current:''}`):s.phase==='error'?tr(`Не удалось обновить индекс: ${s.error}`,`Could not update index: ${s.error}`):s.ready===s.total&&s.total?tr(`✓ Индекс готов: ${s.ready} предметов`,`✓ Index ready: ${s.ready} objects`):tr(`В индексе ${s.ready} / ${s.total}. Требуют обновления: ${s.stale}`,`Indexed ${s.ready} / ${s.total}. Need updating: ${s.stale}`);
  $('#semantic-build').disabled=s.running;$('#semantic-submit').disabled=semanticBusy||s.running||!s.ready;
 }catch(e){$('#semantic-status').textContent=tr('Не удалось проверить индекс: ','Could not check the index: ')+uiText(e.message);}
}
function openSemantic(){page='collection';$('#semantic-panel').hidden=false;render();refreshSemanticStatus();$('#semantic-query').focus();}
$('#semantic-open').onclick=$('#semantic-sidebar').onclick=openSemantic;
$('#semantic-close').onclick=()=>{$('#semantic-panel').hidden=true;};
$('#semantic-build').onclick=async()=>{
 $('#semantic-error').textContent='';try{await api('/api/semantic/build',{});await refreshSemanticStatus();}catch(e){$('#semantic-error').textContent=uiText(e.message);}
};
$('#semantic-reset').onclick=()=>{semanticRequest++;semanticResults=null;semanticQuery='';$('#semantic-query').value='';$('#semantic-error').textContent='';renderCollection();};
$('#semantic-form').onsubmit=async e=>{
 e.preventDefault();const request=++semanticRequest;semanticBusy=true;$('#semantic-submit').disabled=true;$('#semantic-error').textContent='';
 try{
  const query=$('#semantic-query').value.trim(),mode=$('#semantic-mode').value;
  const result=await api('/api/semantic/search',{query,mode,limit:18});
  if(request!==semanticRequest)return;semanticResults=result.matches;semanticQuery=query;category='all';$('#search').value='';$('#filter').value='all';renderCollection();
  if(result.stale)$('#semantic-error').textContent=tr(`${result.stale} предметов изменились и не участвовали в поиске. Обновите индекс.`,`${result.stale} objects changed and were excluded from the search. Update the index.`);
  if(!result.matches.length)$('#semantic-error').textContent=uiText('Подходящих результатов в индексе нет.');
 }catch(error){if(request===semanticRequest)$('#semantic-error').textContent=uiText(error.message);}
 finally{semanticBusy=false;refreshSemanticStatus();}
};
window.addEventListener('beforeunload',e=>{if(dirty.size){e.preventDefault();e.returnValue='';}});
async function boot(){
 await refresh(true);if(!state)return;
 try{const saved=JSON.parse(localStorage.getItem(draftKey)||'null');if(saved?.root===state.root&&saved.edits?.length){$('#recovery').hidden=false;$('#restore-draft').onclick=()=>{for(const edit of saved.edits){const a=asset(edit.key);if(a){Object.assign(a,edit.patch);dirty.set(edit.key,{...edit,seq:++seq,blocked:!edit.base&&edit.revision!==a.revision});}}$('#recovery').hidden=true;draft();render();renderSaveIssues();flush();};$('#dismiss-draft').onclick=()=>{$('#recovery').hidden=true;draft();};}}catch(e){}
 refreshSemanticStatus();if(new URLSearchParams(location.search).has('semantic'))openSemantic();setInterval(()=>{refresh();refreshSemanticStatus();},4000);
}

let directionParent=null;
const directionNames={front:'Спереди',back:'Сзади',left:'Слева',right:'Справа'};
async function openDirections(key){await settled();directionParent=key;const a=asset(key);$('#directions-camera').value=a.perspective||'rpg';$('#directions-error').textContent='';renderDirections();$('#directions-dialog').showModal();}
function directionAsset(face){const base=asset(directionParent);return (base.direction||'front')===face?base:state.assets.find(a=>a.parent_key===base.key&&a.direction===face);}
function renderDirections(){
 const base=asset(directionParent);if(!base)return;const children=state.assets.filter(a=>a.parent_key===base.key);
 $('#directions-views').innerHTML=Object.entries(directionNames).map(([face,ruLabel])=>{const label=tr(ruLabel,({front:'Front',back:'Back',left:'Left',right:'Right'})[face]);const a=directionAsset(face),busy=directionManualBusy||a?.job;return `<article><strong>${label}${a===base?tr(' · образец',' · reference'):''}</strong><div class="direction-stage">${a?.available?`<img src="/thumb?key=${encodeURIComponent(a.key)}${a.output_current?'&processed=1':''}&v=${a.revision}-${a.image?.source_sha256}" alt="${label}">`:tr('Ещё не создан','Not created yet')}</div><p>${esc(a?.job?jobNames[a.job.status]:a?.output_current?tr('PNG собран','PNG built'):a?.available?tr('Нужна обработка','Needs processing'):'')}</p><div class="batch-actions"><button type="button" data-upload-face="${face}" ${busy?'disabled':''} ${iconAttrs('Загрузить и пикселизировать')}>${actionIcon('upload')}</button>${a?.available?`<button type="button" data-process-key="${esc(a.key)}" ${busy?'disabled':''} ${iconAttrs('Пикселизировать заново')}>${actionIcon('pixels')}</button>`:''}${a?.available&&['left','right'].includes(face)?`<button type="button" data-mirror-face="${face}" ${busy?'disabled':''} ${iconAttrs('Отразить '+(face==='left'?'вправо':'влево'))}>${actionIcon('mirror')}</button>`:''}</div>${a?`<button type="button" data-view-key="${esc(a.key)}" ${iconAttrs('Настройки')}>${actionIcon('settings')}</button><button type="button" data-regen-key="${esc(a.key)}" ${busy?'disabled':''} ${iconAttrs('Перегенерировать')}>${actionIcon('refresh')}</button>${a.output_current?` <a ${iconAttrs('Скачать PNG')} href="/png?key=${encodeURIComponent(a.key)}" download>${actionIcon('download')}</a>`:''}`:''}</article>`;}).join('');
 for(const b of $('#directions-views').querySelectorAll('[data-view-key]'))b.onclick=()=>{$('#directions-dialog').close();openAsset(b.dataset.viewKey);};
 for(const b of $('#directions-views').querySelectorAll('[data-regen-key]'))b.onclick=()=>{$('#directions-dialog').close();openAsset(b.dataset.regenKey,true);};
 for(const b of $('#directions-views').querySelectorAll('[data-upload-face]'))b.onclick=()=>{directionUploadFace=b.dataset.uploadFace;$('#direction-file').click();};
 for(const b of $('#directions-views').querySelectorAll('[data-mirror-face]'))b.onclick=()=>manualDirection(b.dataset.mirrorFace,null,true);
 for(const b of $('#directions-views').querySelectorAll('[data-process-key]'))b.onclick=()=>action(async()=>{await settled();await api('/api/enqueue',{keys:[b.dataset.processKey],kind:'process'});await api('/api/start',{});await refresh(true);});
 const busy=directionManualBusy||[base,...children].some(a=>a.job);$('#directions-generate').disabled=busy;$('#directions-generate').textContent=busy?tr('Обработка…','Processing…'):children.length?tr('Перегенерировать 3 направления','Regenerate 3 views'):tr('Создать 3 направления','Create 3 views');
}
let directionManualBusy=false,directionUploadFace=null;
async function manualDirection(face,file,mirror=false){
 if(directionManualBusy)return;directionManualBusy=true;$('#directions-error').textContent='';renderDirections();
 try{
  await settled();const base=asset(directionParent),source=directionAsset(face),targetFace=mirror?(face==='left'?'right':'left'):face,target=directionAsset(targetFace);
  const body={key:base.key,revision:base.revision,direction:targetFace,target_revision:target?.revision};
  if(mirror){body.mirror_from=source.key;body.source_revision=source.revision;}
  else{if(!file||file.size>8_000_000)throw new Error('Выберите PNG, JPEG или WebP до 8 МБ');body.data=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result.split(',')[1]);r.onerror=()=>reject(new Error('Не удалось прочитать файл'));r.readAsDataURL(file);});}
  const result=await api('/api/directions/manual',body);await refresh(true);if(result.warning)$('#directions-error').textContent='Исходник сохранён. '+result.warning;else toast(mirror?'Отражено и пикселизировано':'Загружено и пикселизировано');
 }catch(e){$('#directions-error').textContent=uiText(e.message);}
 finally{directionManualBusy=false;renderDirections();}
}
$('#direction-file').onchange=async e=>{const file=e.target.files[0];e.target.value='';if(file)await manualDirection(directionUploadFace,file);};
$('#directions-generate').onclick=()=>action(async()=>{
 const b=$('#directions-generate');b.disabled=true;$('#directions-error').textContent='';
 try{await settled();const a=asset(directionParent);await api('/api/directions',{key:a.key,revision:a.revision,perspective:$('#directions-camera').value});await api('/api/start',{});await refresh(true);renderDirections();toast('Генерируются три направления по основному образцу');}
 catch(e){$('#directions-error').textContent=uiText(e.message);b.disabled=false;}
});

boot();

const trashButton=document.createElement('button');trashButton.type='button';trashButton.id='trash-open';trashButton.title=uiText('Удалённые предметы');trashButton.innerHTML=actionIcon('trash')+'<span>'+uiText('Корзина')+'</span>';$('#export-settings').parentNode.append(trashButton);
const trashDialog=document.createElement('dialog');trashDialog.innerHTML='<div class="dialog-head"><h2>Корзина мастерской</h2><button type="button" aria-label="Закрыть корзину">×</button></div><div class="form-body trash-list"></div>';document.body.append(trashDialog);trashDialog.querySelector('button').onclick=()=>trashDialog.close();
async function renderTrash(){const data=await api('/api/trash'),list=trashDialog.querySelector('.trash-list');list.replaceChildren();if(!data.entries.length){list.textContent=uiText('Корзина пуста');return;}for(const entry of data.entries){const row=document.createElement('div');row.className='trash-row';const label=document.createElement('div');label.textContent=entry.label+' · '+entry.keys.length+' шт.';const path=document.createElement('small');path.textContent=entry.key;label.append(document.createElement('br'),path);const button=document.createElement('button');button.textContent=uiText('Восстановить');button.onclick=()=>action(async()=>{button.disabled=true;try{await settled();await api('/api/trash/restore',{id:entry.id});semanticResults=null;await refresh(true);await renderTrash();toast('Предмет восстановлен');}finally{button.disabled=false;}});row.append(label,button);list.append(row);}}
trashButton.onclick=()=>action(async()=>{await renderTrash();trashDialog.showModal();});

$('#tiled-export').onclick=async()=>{const button=$('#tiled-export');button.disabled=true;try{await flush();if(dirty.size)throw new Error('Сначала сохраните изменения карточек.');const result=await api('/api/tiled/export',{});const notice=$('#notice');notice.hidden=false;notice.textContent=tr('Экспорт для Tiled: ','Tiled export: ')+result.exported+' PNG. '+result.root+tr(' · В Tiled подключите collection.tsj нужной категории.',' · In Tiled, use the collection.tsj file for the desired category.')+(result.skipped.length?tr(' Пропущено без актуальной сборки: ',' Skipped without a current build: ')+result.skipped.length+'.':'')+(result.retained?tr(' Сохранены прежние версии: ',' Previous versions retained: ')+result.retained+'.':'');toast('Наборы Tiled обновлены');}catch(e){toast(e.message,true);}finally{button.disabled=false;}};

window.addEventListener('workshop-language-change',()=>{if(!state)return;counts();nav();selection();renderQueue();for(const a of visible){const card=cards.get(a.key);if(card)localizeCard(card,a);}if($('#directions-dialog').open)renderDirections();$('#section-title').textContent=category==='all'?tr('Все предметы','All objects'):category;$('#section-count').textContent=tr(`${visible.length} ПРЕДМЕТОВ · ${processed?'ГОТОВЫЕ PNG':'ИСХОДНИКИ'}`,`${visible.length} OBJECTS · ${processed?'FINISHED PNGS':'SOURCES'}`);});
