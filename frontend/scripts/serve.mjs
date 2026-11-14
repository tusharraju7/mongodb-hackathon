import { createServer, request } from 'node:http';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
const root = new URL('../dist/', import.meta.url);
const allowed = { '/': ['index.html','text/html'], '/index.html': ['index.html','text/html'], '/app.js': ['app.js','text/javascript'], '/app.css': ['app.css','text/css'] };
createServer(async (req,res) => {
  const url=new URL(req.url,'http://localhost');
  if(url.pathname.startsWith('/api/')) {
    const upstream=request({hostname:'127.0.0.1',port:8000,path:url.pathname.slice(4)+url.search,method:req.method,
      headers:{...req.headers,host:'127.0.0.1:8000'}}, response=>{
        res.writeHead(response.statusCode??502,response.headers);response.pipe(res);
      });
    upstream.setTimeout(240000,()=>upstream.destroy(new Error('Backend request timed out')));
    upstream.on('error',()=>{if(!res.headersSent)res.writeHead(502,{'Content-Type':'application/json'});res.end(JSON.stringify({message:'Backend unavailable. Start FastAPI on port 8000.'}));});
    req.on('aborted',()=>upstream.destroy());req.pipe(upstream);return;
  }
  const item = allowed[url.pathname];
  if (!item) {res.writeHead(404);res.end('Not found');return;}
  try {const data=await readFile(fileURLToPath(new URL(item[0],root)));res.writeHead(200,{'Content-Type':`${item[1]}; charset=utf-8`,'Cache-Control':'no-store'});res.end(data);}
  catch {res.writeHead(503);res.end('Run npm run build first.');}
}).listen(3000,'127.0.0.1',()=>console.log('Greenlight: http://127.0.0.1:3000'));
