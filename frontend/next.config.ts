import type {NextConfig} from 'next';
const config:NextConfig={output:'export',poweredByHeader:false,images:{unoptimized:true},...(process.env.NODE_ENV==='development'?{rewrites:async()=>[{source:'/api/:path*',destination:'http://127.0.0.1:8000/:path*'}]}:{})};
export default config;
