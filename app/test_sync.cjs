const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
function harness(){
 const nodes=new Map(),storage=new Map(),downloads=[];
 function node(){return {value:'',hidden:false,style:{},parentNode:{append(){}},classList:{toggle(){}},append(){},replaceChildren(){},click(){downloads.push(this.download)},addEventListener(){},elements:{},querySelector(){return node()}};}
 const c={console,document:{body:node(),querySelector(s){if(!nodes.has(s))nodes.set(s,node());return nodes.get(s);},querySelectorAll(){return[]},createElement(){return node()},activeElement:null},localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)},window:{addEventListener(){}},setTimeout(){return 1},clearTimeout(){},setInterval(){},URL:{createObjectURL(){return 'blob:test'},revokeObjectURL(){}},Blob,structuredClone,fetch:async()=>{throw new Error('offline')}};
 vm.createContext(c);let source=fs.readFileSync(__dirname+'/app.js','utf8');source=source.replace(/^boot\(\);\s*$/m,'');vm.runInContext(source,c);
 vm.runInContext("state={root:'/test',assets:[{key:'A/cap',label:'Cap',scale:1,reviewed:false,revision:1,image:{source_sha256:'one'}}],jobs:[],categories:['A']};updateCard=()=>{};counts=()=>{};render=()=>{};",c);
 return {c,nodes,storage,downloads,run:s=>vm.runInContext(s,c)};
}
test('busy object is temporary, retries after completion without losing edits',async()=>{
 const h=harness();let busy=true,posts=0;
 h.c.api=async(path,body)=>{if(path==='/api/asset'){posts++;if(busy)throw Object.assign(new Error('busy'),{status:409});return {key:'A/cap',scale:1.2,reviewed:false,revision:3,image:{source_sha256:'two'}};}return {assets:[{key:'A/cap',scale:1,reviewed:false,revision:busy?1:2,job:busy?{status:'running'}:null,image:{source_sha256:'two'}}]};};
 h.run("editInline('A/cap',{scale:1.2})");await h.run('flush()');assert.equal(h.run("dirty.get('A/cap').blocked"),false);assert.equal(h.run("dirty.get('A/cap').waiting"),true);
 busy=false;await h.run('flush()');assert.equal(h.run('dirty.size'),0);assert.equal(h.run("asset('A/cap').scale"),1.2);assert.equal(posts,2);
});
test('revision change in unrelated fields safely rebases and saves immediately',async()=>{
 const h=harness();let posts=0;
 h.c.api=async(path,body)=>{if(path==='/api/state')return {assets:[{key:'A/cap',scale:1,reviewed:false,revision:2,image:{source_sha256:'one'}}]};if(++posts===1)throw Object.assign(new Error('revision'),{status:409});assert.equal(body.revision,2);return {key:'A/cap',scale:1.3,reviewed:false,revision:3};};
 h.run("editInline('A/cap',{scale:1.3})");await h.run('settled()');assert.equal(h.run('dirty.size'),0);assert.equal(posts,2);
});
test('concurrent edit to same field is not overwritten',async()=>{
 const h=harness();let posts=0;
 h.c.api=async path=>{if(path==='/api/state')return {assets:[{key:'A/cap',scale:1.7,reviewed:false,revision:2,image:{source_sha256:'one'}}]};posts++;throw Object.assign(new Error('revision'),{status:409});};
 h.run("editInline('A/cap',{scale:1.3})");await h.run('flush()');assert.equal(h.run("dirty.get('A/cap').blocked"),true);assert.equal(posts,1);assert.equal(h.nodes.get('#notice').hidden,false);
 await assert.rejects(h.run('settled()'),/Выберите нужную/);assert.equal(posts,1);
});
test('export remains available with conflict, preserves local scale and disk-only changes',async()=>{
 const h=harness();h.c.api=async path=>{assert.equal(path,'/api/settings');return {application:'sprite-workshop',version:1,assets:[{key:'A/cap',scale:1.7,prompt:'new prompt',revision:2}]};};
 h.run("editInline('A/cap',{scale:1.3});dirty.get('A/cap').blocked=true");
 await h.nodes.get('#export-settings').onclick();assert.deepEqual(h.downloads,['sprite-workshop-settings-draft.json']);
 const out=h.run("exportProgress({assets:[{key:'A/cap',scale:1.7,prompt:'new prompt'}]},[{key:'A/cap',patch:{scale:1.3},revision:1}])");assert.equal(out.assets[0].scale,1.3);assert.equal(out.assets[0].prompt,'new prompt');assert.equal(out.pending_edits.length,1);
});
test('export works offline and includes un-restored browser draft',async()=>{
 const h=harness();h.c.api=async()=>{throw Error('offline')};h.storage.set('sprite-workshop-draft-v1',JSON.stringify({root:'/test',edits:[{key:'A/cap',patch:{scale:1.9},revision:1}]}));
 await h.nodes.get('#export-settings').onclick();assert.deepEqual(h.downloads,['sprite-workshop-settings-draft.json']);
});
test('newer input arriving during a save is retained and based on the saved revision',async()=>{
 const h=harness();let reply;h.c.api=async()=>await new Promise(r=>reply=r);
 h.run("editInline('A/cap',{scale:1.2})");const saving=h.run('flush()');h.run("editInline('A/cap',{scale:1.4})");reply({key:'A/cap',scale:1.2,reviewed:false,revision:2,image:{source_sha256:'one'}});await saving;
 assert.equal(h.run("dirty.get('A/cap').patch.scale"),1.4);assert.equal(h.run("dirty.get('A/cap').revision"),2);assert.equal(h.run("dirty.get('A/cap').base.scale"),1.2);
});
test('review approval does not silently transfer to a new source image',()=>{
 const h=harness();assert.equal(h.run("syncDecision({revision:1,patch:{reviewed:true},base:{reviewed:false},sourceSha:'old'},{revision:2,reviewed:false,image:{source_sha256:'new'}})"),'conflict');
});
test('a lost successful save response is recognized without a repeated write',async()=>{
 const h=harness();h.c.api=async path=>{if(path==='/api/state')return {assets:[{key:'A/cap',scale:1.2,reviewed:false,revision:2,image:{source_sha256:'one'}}]};throw Object.assign(new Error('revision'),{status:409});};h.run("editInline('A/cap',{scale:1.2})");await h.run('flush()');assert.equal(h.run('dirty.size'),0);
});
