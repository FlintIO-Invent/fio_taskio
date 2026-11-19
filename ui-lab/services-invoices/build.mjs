// Task-owned build: pinned existing tools, shared approved sources stay read-only.
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
import {execFileSync} from 'node:child_process';
const root=path.dirname(fileURLToPath(import.meta.url));
const lab=path.dirname(root), tools=path.join(lab,'services-dashboard/daisyui');
const require=createRequire(path.join(tools,'package.json'));
const {build}=require('esbuild');
const dist=path.join(root,'dist');
await fs.mkdir(path.join(dist,'assets'),{recursive:true});
execFileSync(path.join(tools,'node_modules/.bin/tailwindcss'),['-i',path.join(root,'src/input.css'),'-o',path.join(dist,'app.css'),'--minify'],{cwd:tools,stdio:'inherit'});
const result=await build({entryPoints:[path.join(root,'src/app.js')],bundle:true,minify:true,format:'esm',target:['chrome123','firefox128','safari17.5'],outfile:path.join(dist,'app.js'),metafile:true});
await fs.writeFile(path.join(root,'build-meta.json'),JSON.stringify(result.metafile,null,2)+'\n');
for (const [from,to] of [
 [path.join(lab,'design-system/tokens.css'),'tokens.css'],
 [path.join(lab,'design-system/initial-theme.js'),'initial-theme.js'],
 [path.join(lab,'services-dashboard/shared/assets/motionmate-logo.svg'),'assets/motionmate-logo.svg'],
 [path.join(lab,'services-dashboard/shared/assets/Feather-MIT.txt'),'assets/Feather-MIT.txt'],
 [path.join(root,'src/index.html'),'index.html'],
]) await fs.copyFile(from,path.join(dist,to));
const font=path.join(tools,'node_modules/@fontsource-variable/manrope');
await fs.copyFile(path.join(font,'files/manrope-latin-wght-normal.woff2'),path.join(dist,'assets/manrope-latin-wght-normal.woff2'));
await fs.copyFile(path.join(font,'LICENSE'),path.join(dist,'assets/Manrope-OFL.txt'));
for(const [pkg,name] of [['daisyui','DaisyUI-MIT.txt'],['tailwindcss','Tailwind-MIT.txt']]) await fs.copyFile(path.join(tools,'node_modules',pkg,'LICENSE'),path.join(dist,'assets',name));
console.log('Built Services Invoices only. Frozen registry, Clients, Appointments and dashboard preserved.');
