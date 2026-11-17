const {test}=require('node:test');
const assert=require('node:assert/strict');
const i18n=require('./i18n.js');

test('language selection defaults to Russian and persists an explicit choice',()=>{
 const values=new Map();const storage={getItem:key=>values.get(key),setItem:(key,value)=>values.set(key,value)};
 assert.equal(i18n.getLanguage(storage),'ru');
 i18n.setLanguage(storage,'en');assert.equal(i18n.getLanguage(storage),'en');
 assert.throws(()=>i18n.setLanguage(storage,'xx'),RangeError);
});
test('translations have matching keys and preserve unknown messages',()=>{
 assert.deepEqual(Object.keys(i18n.messages.ru).sort(),Object.keys(i18n.messages.en).sort());
 assert.equal(i18n.translate('en','nav.queue'),'Queue');
 assert.equal(i18n.translate('en','unknown.key'),'unknown.key');
 assert.equal(i18n.translateError('en','Предмет не найден'),'Object not found');
 assert.equal(i18n.translateError('en','Неизвестная ошибка: example'),'Неизвестная ошибка: example');
});
test('storage failures keep language selection usable',()=>{
 const storage={getItem(){throw Error('unavailable')},setItem(){throw Error('unavailable')}};
 assert.equal(i18n.getLanguage(storage),'ru');assert.equal(i18n.setLanguage(storage,'en'),'en');
});
