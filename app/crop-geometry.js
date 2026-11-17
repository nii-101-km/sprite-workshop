'use strict';
const CropGeometry={
 clamp:(v,a,b)=>Math.max(a,Math.min(b,v)),
 point(clientX,clientY,bounds,width,height){return [this.clamp(Math.round((clientX-bounds.left)*width/bounds.width),0,width),this.clamp(Math.round((clientY-bounds.top)*height/bounds.height),0,height)];},
 rectangle(a,b){return [Math.min(a[0],b[0]),Math.min(a[1],b[1]),Math.abs(a[0]-b[0]),Math.abs(a[1]-b[1])];},
 move(rect,dx,dy,width,height){return [this.clamp(rect[0]+dx,0,width-rect[2]),this.clamp(rect[1]+dy,0,height-rect[3]),rect[2],rect[3]];},
 grid(width,height,cols,rows){const out=[];for(let r=0;r<rows;r++)for(let c=0;c<cols;c++){const x=Math.round(c*width/cols),y=Math.round(r*height/rows);out.push([x,y,Math.round((c+1)*width/cols)-x,Math.round((r+1)*height/rows)-y]);}return out;},
 hit(rect,x,y){return x>=rect[0]&&x<=rect[0]+rect[2]&&y>=rect[1]&&y<=rect[1]+rect[3];}
};
if(typeof module!=='undefined')module.exports=CropGeometry;
