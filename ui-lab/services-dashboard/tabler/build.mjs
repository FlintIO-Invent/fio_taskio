import fs from 'node:fs/promises';import path from 'node:path';import{fileURLToPath}from'node:url';import{build}from'esbuild';import{prepare,html}from'../shared/build.mjs';
const root=path.dirname(fileURLToPath(import.meta.url));const dist=await prepare(root);
await fs.copyFile(path.join(root,'node_modules/@tabler/core/dist/css/tabler.min.css'),path.join(dist,'tabler.min.css'));
await fs.copyFile(path.join(root,'Tabler-MIT.txt'),path.join(dist,'assets/Tabler-MIT.txt'));
await build({entryPoints:[path.join(root,'src/app.js')],bundle:true,minify:true,format:'esm',target:['chrome123','firefox128','safari17.5'],outfile:path.join(dist,'app.js'),metafile:true}).then(r=>fs.writeFile(path.join(root,'build-meta.json'),JSON.stringify(r.metafile,null,2)));
await build({entryPoints:[path.join(root,'src/style.css')],bundle:false,minify:true,outfile:path.join(dist,'app.css')});
await fs.writeFile(path.join(dist,'index.html'),html('app.css','<link rel="stylesheet" href="./tabler.min.css">'));
console.log('Tabler standalone build ready');
