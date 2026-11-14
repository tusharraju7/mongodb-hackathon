import { build, context } from 'esbuild';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
process.chdir(fileURLToPath(new URL('../', import.meta.url)));
const dev = process.argv.includes('--dev');
const options = { entryPoints: ['src/main.tsx'], bundle: true, outfile: 'dist/app.js', format: 'iife', minify: !dev, sourcemap: dev, jsx: 'automatic', target: ['es2022'], loader: { '.png': 'dataurl' }, define: { 'process.env.NODE_ENV': JSON.stringify(dev ? 'development' : 'production') }, legalComments: 'eof' };
await mkdir('dist', { recursive: true });
const shell = await readFile('index.html', 'utf8');
await writeFile('dist/index.html', shell.replace('<!-- STYLES -->', '<link rel="stylesheet" href="./app.css">').replace('<!-- SCRIPT -->', '<script defer src="./app.js"></script>'));
if (dev) {
  const ctx = await context(options);
  await ctx.watch();
  const server = await ctx.serve({ servedir: 'dist', host: '127.0.0.1', port: 3000 });
  console.log(`Greenlight: http://127.0.0.1:${server.port} (refresh after edits)`);
} else {
  await build(options);
  const js = (await readFile('dist/app.js', 'utf8')).replace(/<\/script/gi, '<\\/script');
  const css = (await readFile('dist/app.css', 'utf8')).replace(/<\/style/gi, '<\\/style');
  await mkdir('share', { recursive: true });
  await writeFile('share/greenlight-demo.html', shell.replace('<!-- STYLES -->', () => `<style>${css}</style>`).replace('<!-- SCRIPT -->', () => `<script>${js}</script>`));
  console.log(`Built dist/ and ${resolve('share/greenlight-demo.html')}`);
}
