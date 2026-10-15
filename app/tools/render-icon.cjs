// Renders app/renderer/assets/overseer.svg to the window / shortcut icons: app/assets/icon.png (256 px) and
// app/assets/icon.ico (16-256 px, PNG frames). Run after changing the SVG:  npx electron app/tools/render-icon.cjs
const { app, BrowserWindow } = require('electron');
const fs = require('fs');
const path = require('path');

const SVG = path.join(__dirname, '..', 'renderer', 'assets', 'overseer.svg');
const OUT = path.join(__dirname, '..', 'assets');
const SIZES = [16, 24, 32, 48, 64, 128, 256];

function ico(pngs) {   // ICONDIR + ICONDIRENTRY per image, PNG data as is (Windows Vista and later)
  const head = Buffer.alloc(6 + 16 * pngs.length);
  head.writeUInt16LE(0, 0); head.writeUInt16LE(1, 2); head.writeUInt16LE(pngs.length, 4);
  let offset = head.length;
  pngs.forEach(([size, png], i) => {
    const e = 6 + 16 * i;
    head.writeUInt8(size >= 256 ? 0 : size, e); head.writeUInt8(size >= 256 ? 0 : size, e + 1);
    head.writeUInt16LE(1, e + 4); head.writeUInt16LE(32, e + 6);
    head.writeUInt32LE(png.length, e + 8); head.writeUInt32LE(offset, e + 12);
    offset += png.length;
  });
  return Buffer.concat([head, ...pngs.map(([, png]) => png)]);
}

app.whenReady().then(async () => {
  const svg = fs.readFileSync(SVG, 'utf8');
  const win = new BrowserWindow({ show: false, width: 256, height: 256, frame: false, transparent: true,
    webPreferences: { offscreen: true } });
  const pngs = [];
  for (const size of SIZES) {
    const html = `<html><body style="margin:0;background:transparent;overflow:hidden">
      <img src="data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}" width="${size}" height="${size}"></body></html>`;
    win.setContentSize(size, size);
    await win.loadURL(`data:text/html;base64,${Buffer.from(html).toString('base64')}`);
    await new Promise((r) => setTimeout(r, 150));
    const image = await win.webContents.capturePage({ x: 0, y: 0, width: size, height: size });
    pngs.push([size, image.resize({ width: size, height: size, quality: 'best' }).toPNG()]);
  }
  fs.mkdirSync(OUT, { recursive: true });
  fs.writeFileSync(path.join(OUT, 'icon.png'), pngs.at(-1)[1]);
  fs.writeFileSync(path.join(OUT, 'icon.ico'), ico(pngs));
  console.log(`icon.png + icon.ico (${SIZES.join(', ')} px) in ${OUT}`);
  app.quit();
});
