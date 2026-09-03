// Ícones do app Painel B3: LOGO ORIGINAL da Insignia (brand/logo_full.png) sobre
// candlesticks na paleta da marca. PNG puro via zlib, supersampling 4x — sem libs externas.
// Uso:  node gen_icons.mjs          (logo completo)
//       ICONE=MONO node gen_icons.mjs   (monograma IN)
import fs from 'fs';
import zlib from 'zlib';

function readPNG(file){
  const b=fs.readFileSync(file);
  let i=8, W=0,H=0,depth=8,ct=6, idat=[], plte=null, trns=null;
  while(i<b.length){
    const len=b.readUInt32BE(i), type=b.slice(i+4,i+8).toString('ascii'), d=b.slice(i+8,i+8+len);
    if(type==='IHDR'){ W=d.readUInt32BE(0); H=d.readUInt32BE(4); depth=d[8]; ct=d[9]; }
    else if(type==='IDAT') idat.push(d);
    else if(type==='PLTE') plte=d;
    else if(type==='tRNS') trns=d;
    else if(type==='IEND') break;
    i+=12+len;
  }
  if(depth!==8) throw new Error('bitdepth '+depth+' nao suportado');
  const raw=zlib.inflateSync(Buffer.concat(idat));
  const ch = ct===2?3 : ct===6?4 : ct===0?1 : ct===4?2 : ct===3?1 : 0;
  if(!ch) throw new Error('colortype '+ct);
  const stride=W*ch;
  const out=Buffer.alloc(H*stride);
  let prev=Buffer.alloc(stride);
  for(let y=0;y<H;y++){
    const f=raw[y*(stride+1)];
    const line=raw.slice(y*(stride+1)+1, y*(stride+1)+1+stride);
    const cur=Buffer.alloc(stride);
    for(let x=0;x<stride;x++){
      const a = x>=ch ? cur[x-ch] : 0, bb = prev[x], c = x>=ch ? prev[x-ch] : 0;
      let v=line[x];
      if(f===1) v+=a; else if(f===2) v+=bb; else if(f===3) v+=(a+bb)>>1;
      else if(f===4){ const p=a+bb-c, pa=Math.abs(p-a), pb=Math.abs(p-bb), pc=Math.abs(p-c);
        v += (pa<=pb&&pa<=pc)?a:(pb<=pc?bb:c); }
      cur[x]=v&255;
    }
    cur.copy(out,y*stride); prev=cur;
  }
  // normaliza para RGBA
  const px=Buffer.alloc(W*H*4);
  for(let p=0;p<W*H;p++){
    let r,g,bl,al=255;
    if(ct===2){ r=out[p*3]; g=out[p*3+1]; bl=out[p*3+2]; }
    else if(ct===6){ r=out[p*4]; g=out[p*4+1]; bl=out[p*4+2]; al=out[p*4+3]; }
    else if(ct===0){ r=g=bl=out[p]; }
    else if(ct===4){ r=g=bl=out[p*2]; al=out[p*2+1]; }
    else if(ct===3){ const ix=out[p]; r=plte[ix*3]; g=plte[ix*3+1]; bl=plte[ix*3+2]; if(trns&&ix<trns.length) al=trns[ix]; }
    px[p*4]=r; px[p*4+1]=g; px[p*4+2]=bl; px[p*4+3]=al;
  }
  return {W,H,px};
}
function writePNG(W,H,px){
  const raw=Buffer.alloc((W*4+1)*H);
  for(let y=0;y<H;y++){ raw[y*(W*4+1)]=0; px.copy(raw,y*(W*4+1)+1,y*W*4,(y+1)*W*4); }
  const tbl=[]; for(let n=0;n<256;n++){let c=n;for(let k=0;k<8;k++)c=c&1?0xedb88320^(c>>>1):c>>>1;tbl[n]=c>>>0;}
  const crc=bf=>{let c=0xffffffff;for(const v of bf)c=tbl[(c^v)&0xff]^(c>>>8);return (c^0xffffffff)>>>0;};
  const chunk=(t,d)=>{const l=Buffer.alloc(4);l.writeUInt32BE(d.length);
    const td=Buffer.concat([Buffer.from(t,'ascii'),d]);const cr=Buffer.alloc(4);cr.writeUInt32BE(crc(td));
    return Buffer.concat([l,td,cr]);};
  const ihdr=Buffer.alloc(13); ihdr.writeUInt32BE(W,0); ihdr.writeUInt32BE(H,4); ihdr[8]=8; ihdr[9]=6;
  return Buffer.concat([Buffer.from([137,80,78,71,13,10,26,10]),chunk('IHDR',ihdr),
    chunk('IDAT',zlib.deflateSync(raw,{level:9})),chunk('IEND',Buffer.alloc(0))]);
}

// ---- lê um PNG de marca (branco + alpha) e devolve a máscara de cobertura ----
function mascaraDoPNG(caminho){
  const img = readPNG(caminho);
  const a = new Float32Array(img.W * img.H);
  for(let i = 0; i < img.W * img.H; i++) a[i] = img.px[i*4+3] / 255;
  return {W: img.W, H: img.H, a};
}
// amostragem bilinear com realce de borda (mantém os traços nítidos ao ampliar)
function amostra(m, u, v){
  const x = u*(m.W-1), y = v*(m.H-1);
  const x0 = Math.floor(x), y0 = Math.floor(y);
  const x1 = Math.min(m.W-1, x0+1), y1 = Math.min(m.H-1, y0+1);
  const fx = x-x0, fy = y-y0, p = (xx,yy) => m.a[yy*m.W+xx];
  const v0 = p(x0,y0)*(1-fx) + p(x1,y0)*fx;
  const v1 = p(x0,y1)*(1-fx) + p(x1,y1)*fx;
  let t = v0*(1-fy) + v1*fy;
  const k = 0.5, w = 0.30;
  t = Math.max(0, Math.min(1, (t-(k-w))/(2*w)));
  return t*t*(3-2*t);
}
// Ícones do app: LOGO ORIGINAL da Insignia (extraído do material de marca em 1920px)
// sobre candlesticks. PNG puro, supersampling 4x.

const C = { dark:[12,42,45], darker:[7,26,28], deep:[24,73,78],
            ink:[245,252,248], lime:[203,221,127], gold:[220,182,4], sage:[99,136,118] };

function encodePNG(size, px){
  const raw=Buffer.alloc((size*4+1)*size);
  for(let y=0;y<size;y++){ raw[y*(size*4+1)]=0; px.copy(raw,y*(size*4+1)+1,y*size*4,(y+1)*size*4); }
  const tbl=[]; for(let n=0;n<256;n++){let c=n;for(let k=0;k<8;k++)c=c&1?0xedb88320^(c>>>1):c>>>1;tbl[n]=c>>>0;}
  const crc=b=>{let c=0xffffffff;for(const v of b)c=tbl[(c^v)&0xff]^(c>>>8);return (c^0xffffffff)>>>0;};
  const ch=(t,d)=>{const l=Buffer.alloc(4);l.writeUInt32BE(d.length);
    const td=Buffer.concat([Buffer.from(t,'ascii'),d]);const cr=Buffer.alloc(4);cr.writeUInt32BE(crc(td));
    return Buffer.concat([l,td,cr]);};
  const ihdr=Buffer.alloc(13); ihdr.writeUInt32BE(size,0); ihdr.writeUInt32BE(size,4); ihdr[8]=8; ihdr[9]=6;
  return Buffer.concat([Buffer.from([137,80,78,71,13,10,26,10]),ch('IHDR',ihdr),
    ch('IDAT',zlib.deflateSync(raw,{level:9})),ch('IEND',Buffer.alloc(0))]);
}

function Canvas(S){
  const px=Buffer.alloc(S*S*4);
  const put=(x,y,c,a)=>{ if(x<0||y<0||x>=S||y>=S||a<=0) return;
    const i=(y*S+x)*4, ia=1-a;
    px[i]=Math.round(c[0]*a+px[i]*ia); px[i+1]=Math.round(c[1]*a+px[i+1]*ia);
    px[i+2]=Math.round(c[2]*a+px[i+2]*ia); px[i+3]=Math.round(255*a+px[i+3]*ia); };
  const R=(x,y,w,h,c,a=1)=>{ for(let yy=Math.floor(y);yy<Math.ceil(y+h);yy++)
      for(let xx=Math.floor(x);xx<Math.ceil(x+w);xx++) put(xx,yy,c,a); };
  return {S,px,put,rect:R,
    line:(x0,y0,x1,y1,w,c,a=1)=>{ const dx=x1-x0,dy=y1-y0,L=Math.hypot(dx,dy)||1;
      const nx=-dy/L*w/2, ny=dx/L*w/2;
      const pts=[[x0+nx,y0+ny],[x1+nx,y1+ny],[x1-nx,y1-ny],[x0-nx,y0-ny]];
      const ys=pts.map(p=>p[1]); const yA=Math.max(0,Math.floor(Math.min(...ys))), yB=Math.min(S-1,Math.ceil(Math.max(...ys)));
      for(let y=yA;y<=yB;y++){ const xs=[];
        for(let i=0;i<4;i++){const [ax,ay]=pts[i],[bx,by]=pts[(i+1)%4];
          if((ay<=y&&by>y)||(by<=y&&ay>y)) xs.push(ax+(y-ay)/(by-ay)*(bx-ax));}
        xs.sort((p,q)=>p-q);
        for(let k=0;k+1<xs.length;k+=2) for(let x=Math.floor(xs[k]);x<Math.ceil(xs[k+1]);x++) put(x,y,c,a); } }};
}

function fundo(cv,S,rounded){
  const r=rounded?S*0.22:0;
  const dentro=(x,y)=>{ if(!r) return true;
    const cx=x<r?r:(x>S-r?S-r:x), cy=y<r?r:(y>S-r?S-r:y);
    if(cx===x&&cy===y) return true; return Math.hypot(x-cx,y-cy)<=r; };
  for(let y=0;y<S;y++) for(let x=0;x<S;x++){
    if(!dentro(x+0.5,y+0.5)) continue;
    const t=x/S*0.55+y/S*0.45;
    let c; if(t<0.45){const u=t/0.45; c=[0,1,2].map(i=>C.deep[i]+(C.dark[i]-C.deep[i])*u);}
    else {const u=(t-0.45)/0.55; c=[0,1,2].map(i=>C.dark[i]+(C.darker[i]-C.dark[i])*u);}
    cv.put(x,y,c.map(Math.round),1);
  }
}

// desenha a máscara do logo no retângulo (x,y,w,h)
function desenhaLogo(cv,S,m,x,y,w,h,cor){
  for(let yy=Math.max(0,Math.floor(y)); yy<Math.min(S,Math.ceil(y+h)); yy++)
    for(let xx=Math.max(0,Math.floor(x)); xx<Math.min(S,Math.ceil(x+w)); xx++){
      const u=(xx+0.5-x)/w, v=(yy+0.5-y)/h;
      if(u<0||u>1||v<0||v>1) continue;
      const t=amostra(m,u,v);
      if(t>0.003) cv.put(xx,yy,cor,t);
    }
}

function candles(cv,S,x0,x1,yBase,altMax,alpha){
  const defs=[[0.34,1],[0.28,0],[0.48,1],[0.42,0],[0.66,1],[0.58,0],[0.92,1]];
  const larg=(x1-x0)/defs.length, corpoW=larg*0.46;
  defs.forEach((d,i)=>{
    const cx=x0+larg*(i+0.5), alt=altMax*d[0], top=yBase-alt, cor=d[1]?C.lime:C.gold;
    cv.line(cx,top-alt*0.15,cx,yBase+alt*0.03,Math.max(1,S*0.009),cor,alpha);
    if(d[1]) cv.rect(cx-corpoW/2,top+alt*0.12,corpoW,alt*0.62,cor,alpha);
    else cv.rect(cx-corpoW/2,top+alt*0.12,corpoW,alt*0.62,cor,alpha*0.85);
  });
}

function grade(cv,S,y0,y1,alpha){
  for(let i=1;i<=3;i++){ const y=y0+(y1-y0)*i/4;
    cv.rect(S*0.10,y,S*0.80,Math.max(1,S*0.004),C.sage,alpha); }
}

const M = { COMPLETO: mascaraDoPNG('brand/logo_full.png'), IN: mascaraDoPNG('brand/logo_mark.png') };

const VAR = {
  // MONO — monograma IN do logo original, grande e legível
  MONO(cv,S,mask){ fundo(cv,S,!mask);
    const k=mask?0.80:1, off=mask?S*0.10:0;
    grade(cv,S,S*0.60+off*0.35,S*0.86-off*0.35,0.18);
    candles(cv,S,S*0.13+off,S*0.87-off,S*0.865-off*0.45,S*0.30*k,0.62);
    const m=M.IN, h=S*0.34*k, w=h*(m.W/m.H);
    desenhaLogo(cv,S,m,(S-w)/2, S*0.15+off*0.5, w, h, C.ink); },
  // WORD — logo completo INSIGNIA PARTNERS
  WORD(cv,S,mask){ fundo(cv,S,!mask);
    const k=mask?0.80:1, off=mask?S*0.10:0;
    grade(cv,S,S*0.60+off*0.35,S*0.87-off*0.35,0.18);
    candles(cv,S,S*0.13+off,S*0.87-off,S*0.875-off*0.45,S*0.29*k,0.62);
    const m=M.COMPLETO, w=S*0.76*k, h=w*(m.H/m.W);
    desenhaLogo(cv,S,m,(S-w)/2, S*0.22+off*0.4, w, h, C.ink); },
};

function render(nome,S,mask){
  const F=4, big=S*F, cv=Canvas(big);
  VAR[nome](cv,big,mask);
  const out=Buffer.alloc(S*S*4);
  for(let y=0;y<S;y++) for(let x=0;x<S;x++){
    let r=0,g=0,b=0,a=0;
    for(let dy=0;dy<F;dy++) for(let dx=0;dx<F;dx++){
      const i=((y*F+dy)*big+(x*F+dx))*4;
      r+=cv.px[i]; g+=cv.px[i+1]; b+=cv.px[i+2]; a+=cv.px[i+3]; }
    const n=F*F, o=(y*S+x)*4;
    out[o]=Math.round(r/n); out[o+1]=Math.round(g/n); out[o+2]=Math.round(b/n); out[o+3]=Math.round(a/n);
  }
  return encodePNG(S,out);
}


// ---- gera os arquivos ----
const OUT = 'docs/app/';
const ESCOLHA = process.env.ICONE || 'WORD';   // WORD = logo completo | MONO = monograma IN
fs.writeFileSync(OUT + 'icon-192.png',  render(ESCOLHA, 192, false));
fs.writeFileSync(OUT + 'icon-512.png',  render(ESCOLHA, 512, false));
fs.writeFileSync(OUT + 'icon-1024.png', render(ESCOLHA, 1024, false));
fs.writeFileSync(OUT + 'icon-maskable-512.png', render(ESCOLHA, 512, true));
for(const f of ['icon-192.png','icon-512.png','icon-1024.png','icon-maskable-512.png'])
  console.log(f, fs.statSync(OUT+f).size, 'bytes');
