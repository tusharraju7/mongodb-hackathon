'use client';
import dynamic from 'next/dynamic';
const ChatApp=dynamic(()=>import('../src/App'),{ssr:false,loading:()=> <main className="fatal">Loading Greenlight…</main>});
export default function Page(){return <ChatApp/>;}
