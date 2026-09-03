// Gera ícones PNG do app (sem libs externas): PNG puro via zlib do Node
import fs from 'fs';
import zlib from 'zlib';

function png(size, draw) {
  const px = Buffer.alloc(size * size * 4);
  draw((x, y, r, g, b, a = 255) => {
    const i = (y * size + x) * 4;
    px[i] = r; px[i+1] = g; px[i+2] = b; px[i+3] = a;
  });
  // filtro 0 por linha
  const raw = Buffer.alloc((size * 4 + 1) * size);
  for (let y = 0; y < size; y++) {
    raw[y * (size * 4 + 1)] = 0;
    px.copy(raw, y * (size * 4 + 1) + 1, y * size * 4, (y + 1) * size * 4);
  }
  const crcTable = [];
  for (let n = 0; n < 256; n++) { let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    crcTable[n] = c >>> 0; }
  const crc = buf => { let c = 0xffffffff;
    for (const b of buf) c = crcTable[(c ^ b) & 0xff] ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0; };
  const chunk = (type, data) => {
    const len = Buffer.alloc(4); len.writeUInt32BE(data.length);
    const td = Buffer.concat([Buffer.from(type, 'ascii'), data]);
    const cr = Buffer.alloc(4); cr.writeUInt32BE(crc(td));
    return Buffer.concat([len, td, cr]);
  };
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0); ihdr.writeUInt32BE(size, 4);
  ihdr[8] = 8; ihdr[9] = 6; ihdr[10] = 0; ihdr[11] = 0; ihdr[12] = 0;
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr), chunk('IDAT', zlib.deflateSync(raw, {level: 9})), chunk('IEND', Buffer.alloc(0)),
  ]);
}

// desenho: fundo escuro + barras de candlestick estilizadas (verde/laranja)
function desenho(size, maskable) {
  const pad = maskable ? Math.round(size * 0.18) : Math.round(size * 0.10);
  const bg = [12, 42, 45];       // #0c2a2d (mesmo tom escuro do painel)
  const barras = [
    {x: 0.10, h: 0.34, cor: [99, 136, 118]},
    {x: 0.34, h: 0.58, cor: [203, 221, 127]},
    {x: 0.58, h: 0.44, cor: [220, 182, 4]},
    {x: 0.79, h: 0.72, cor: [203, 221, 127]},
  ];
  return set => {
    const raio = size * 0.22;
    for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
      // cantos arredondados (só no ícone normal; maskable é quadrado cheio)
      let dentro = true;
      if (!maskable) {
        const cx = Math.min(x, size - 1 - x), cy = Math.min(y, size - 1 - y);
        if (cx < raio && cy < raio) {
          const dx = raio - cx, dy = raio - cy;
          if (dx * dx + dy * dy > raio * raio) dentro = false;
        }
      }
      if (!dentro) { set(x, y, 0, 0, 0, 0); continue; }
      set(x, y, bg[0], bg[1], bg[2]);
    }
    const area = size - pad * 2;
    for (const b of barras) {
      const bx = Math.round(pad + b.x * area);
      const bw = Math.max(2, Math.round(area * 0.13));
      const bh = Math.round(area * b.h);
      const by = Math.round(pad + area - bh);
      // pavio
      const wx = bx + Math.floor(bw / 2);
      const wtop = Math.max(pad, by - Math.round(area * 0.09));
      for (let y = wtop; y < Math.min(size - pad, by + bh + Math.round(area * 0.07)); y++)
        for (let dx = 0; dx < Math.max(1, Math.round(bw * 0.16)); dx++)
          if (wx + dx < size) set(wx + dx, y, b.cor[0], b.cor[1], b.cor[2]);
      // corpo
      for (let y = by; y < by + bh; y++)
        for (let x = bx; x < bx + bw && x < size; x++)
          if (y >= 0 && y < size) set(x, y, b.cor[0], b.cor[1], b.cor[2]);
    }
  };
}

fs.mkdirSync('docs/app', {recursive: true});
for (const [nome, size, maskable] of [
  ['icon-192.png', 192, false], ['icon-512.png', 512, false],
  ['icon-maskable-512.png', 512, true], ['icon-1024.png', 1024, false]]) {
  fs.writeFileSync('docs/app/' + nome, png(size, desenho(size, maskable)));
  console.log(nome, (fs.statSync('docs/app/' + nome).size / 1024).toFixed(1) + ' KB');
}
