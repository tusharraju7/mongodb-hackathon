import {useState} from 'react';
import type {MemoryChange} from './types';
export function MemoryChangeCard({change,busy,onConfirm,onCancel}:{change:MemoryChange;busy:boolean;onConfirm:(reason:string,password:string)=>Promise<void>;onCancel:()=>void}) {
  const [reason,setReason]=useState('');
  const [password,setPassword]=useState('');
  return <section className="review-actions" aria-label="Proposed memory change">
    <h3>{change.target==='fundamental'?'Proposed policy change':'Proposed memory change'}</h3>
    <p className="small muted">{change.scope?.user_id?'Personal memory':'Team knowledge'} · Nothing is saved until you confirm.</p>
    {change.before&&<details><summary>Current text</summary><p>{change.before}</p></details>}
    <p>{change.action==='forget'?'This memory will be marked forgotten and excluded from future retrieval.':change.after}</p>
    <label>Reason<textarea value={reason} onChange={e=>setReason(e.target.value)} rows={2} disabled={busy}/></label>
    {change.requires_password&&<label>Confirm with your password<input type="password" autoComplete="current-password" value={password} onChange={e=>setPassword(e.target.value)} disabled={busy}/></label>}
    <p className="small muted">Your password goes only to the authenticated change endpoint, never to the chatbot.</p>
    <div className="button-row"><button className="secondary" onClick={onCancel} disabled={busy}>Cancel change</button><button className="primary" disabled={busy||!reason.trim()||(change.requires_password&&!password)} onClick={async()=>{try{await onConfirm(reason.trim(),password);}finally{setPassword('');}}}>Confirm memory change</button></div>
  </section>;
}
