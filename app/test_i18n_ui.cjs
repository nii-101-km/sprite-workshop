const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const i18n=require('./i18n.js');

test('switches fixed controls and keeps user data unchanged',()=>{
 const values=new Map();const storage={getItem:k=>values.get(k),setItem:(k,v)=>values.set(k,v)};
 const button={textContent:'Очередь'};const userData={textContent:'Очередь'};let selector;
 const header={querySelector(){return null},append(el){selector=el}};
 function element(){return {style:{},append(){},setAttribute(){},addEventListener(name,cb){this[name]=cb}};}
 const document={documentElement:{},querySelector(s){return s==='header'?header:s==='#queue-open'?button:null},createElement:element};
 const window={WorkshopI18n:i18n,localStorage:storage,addEventListener(){}};
 vm.runInNewContext(fs.readFileSync(__dirname+'/i18n-ui.js','utf8'),{window,document});
 assert.equal(button.textContent,'Очередь');selector.value='en';selector.change();
 assert.equal(button.textContent,'Queue');assert.equal(userData.textContent,'Очередь');assert.equal(document.documentElement.lang,'en');
 selector.value='ru';selector.change();assert.equal(button.textContent,'Очередь');
});
