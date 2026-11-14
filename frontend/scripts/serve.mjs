import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
const root = new URL('../dist/', import.meta.url);
const allowed = { '/': ['index.html','text/html'], '/index.html': ['index.html','text/html'], '/app.js': ['app.js','text/javascript'], '/app.css': ['app.css','text/css'] };
createServer(async (req,res) => {
  const item = allowed[new URL(req.url,'http://localhost').pathname];
  if (!item) {res.writeHead(404);res.end('Not found');return;}
  try {const data=await readFile(fileURLToPath(new URL(item[0],root)));res.writeHead(200,{'Content-Type':`${item[1]}; charset=utf-8`,'Cache-Control':'no-store'});res.end(data);}
  catch {res.writeHead(503);res.end('Run npm run build first.');}
}).listen(3000,'127.0.0.1',()=>console.log('Greenlight: http://127.0.0.1:3000'));
