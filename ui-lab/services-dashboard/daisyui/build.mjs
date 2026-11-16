import fs from'node:fs/promises';import path from'node:path';import{fileURLToPath}from'node:url';import{execFileSync}from'node:child_process';import{build}from'esbuild';import{prepare,html}from'../shared/build.mjs';
const root=path.dirname(fileURLToPath(import.meta.url));const dist=await prepare(root);
execFileSync(path.join(root,'node_modules/.bin/tailwindcss'),['-i',path.join(root,'src/input.css'),'-o',path.join(dist,'app.css'),'--minify'],{cwd:root,stdio:'inherit'});
await build({entryPoints:[path.join(root,'src/app.js')],bundle:true,minify:true,format:'esm',target:['chrome123','firefox128','safari17.5'],outfile:path.join(dist,'app.js'),metafile:true}).then(r=>fs.writeFile(path.join(root,'build-meta.json'),JSON.stringify(r.metafile,null,2)));
const fontRoot=path.join(root,'node_modules/@fontsource-variable/manrope');
await fs.copyFile(path.join(fontRoot,'files/manrope-latin-wght-normal.woff2'),path.join(dist,'assets/manrope-latin-wght-normal.woff2'));
await fs.copyFile(path.join(fontRoot,'LICENSE'),path.join(dist,'assets/Manrope-OFL.txt'));
// Set the comparison font before CSS loads. This preference belongs to this document only.
const fontScript=`<script>document.documentElement.dataset.font=new URLSearchParams(location.search).get('font')==='nunito'?'nunito':'manrope';</script>`;
await fs.writeFile(path.join(dist,'index.html'),html('app.css').replace('<link rel="stylesheet" href="./tokens.css">',fontScript+'<link rel="stylesheet" href="./tokens.css">'));
console.log('DaisyUI standalone build ready');

for(const [pkg,name] of [['daisyui','DaisyUI-MIT.txt'],['tailwindcss','Tailwind-MIT.txt']])await fs.copyFile(path.join(root,'node_modules',pkg,'LICENSE'),path.join(dist,'assets',name));
