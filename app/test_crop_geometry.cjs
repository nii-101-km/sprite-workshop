const test=require('node:test'),assert=require('node:assert/strict'),G=require('./crop-geometry.js');
test('Pointer coordinates respect CSS scale and canvas origin',()=>{assert.deepEqual(G.point(260,150,{left:10,top:25,width:500,height:250},1000,500),[500,250]);assert.deepEqual(G.point(-20,900,{left:10,top:25,width:500,height:250},1000,500),[0,500]);});
test('Drawing in reverse direction gives positive source rectangle',()=>{assert.deepEqual(G.rectangle([800,900],[200,100]),[200,100,600,800]);});
test('Moving cannot crop outside source bounds',()=>{assert.deepEqual(G.move([50,60,100,200],500,-100,640,480),[540,0,100,200]);});
test('Nondivisible grid covers all source pixels once in row-major order',()=>{const rects=G.grid(1025,1027,4,3);assert.equal(rects.length,12);assert.deepEqual(rects[0],[0,0,256,342]);assert.equal(rects.at(-1)[0]+rects.at(-1)[2],1025);assert.equal(rects.at(-1)[1]+rects.at(-1)[3],1027);assert.equal(rects.reduce((n,r)=>n+r[2]*r[3],0),1025*1027);});
