import type {Metadata} from 'next';
import type {ReactNode} from 'react';
import '../src/styles.css';
export const metadata:Metadata={title:'Greenlight · Ad review',description:'Policy-first creative review in a conversation.'};
export default function Layout({children}:{children:ReactNode}){return <html lang="en"><body>{children}</body></html>;}
