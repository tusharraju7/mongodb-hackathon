import {useState} from 'react';
import {Check, ChevronDown, LocateFixed, ShieldCheck, AlertTriangle, Image as ImageIcon} from 'lucide-react';
import type {Annotation, Review} from './types';
import {detailText, readable, validAnnotation} from './domain';
import {demoRegions} from './demo';
export function ReviewCard({review, live}: {review: Review; live: boolean}) {
  const [selected,setSelected]=useState<string>();
  const [imageFailed,setImageFailed]=useState(false);
  const report=review.report;
  let annotations: Annotation[]=(report?.annotations ?? []).filter(validAnnotation);
  if(!live && review.demoId && review.demoId!=='breaks' && !annotations.length) {
    const refs=review.demoId==='bonus'?['REG-12','REG-13']:['REG-14','REG-09'];
    annotations=refs.map((ref,i)=>{const box=demoRegions[ref];return {id:`demo-${i}`,finding_ref:ref,label:ref,kind:review.demoId==='bonus'?'issue':'evidence',box:{x:box.left/100,y:box.top/100,width:box.width/100,height:box.height/100}};});
  }
  const visible=annotations.filter(a=>a.kind==='issue'||a.finding_ref===selected);
  const locate=(ref: string)=>annotations.some(a=>a.finding_ref===ref) && !!review.image && !imageFailed;
  const onlyInternal=!!report?.violations.length && report.violations.every(v=>v.source==='memory');
  const passedChecks=report?.passed_checks.map((c,i)=>{const ref=c.check.split(' · ')[0];return <details className="policy" key={i}><summary><Check size={16}/><span>{c.check}</span><ChevronDown size={14}/></summary><div className="policy-body"><p>{detailText(c.detail)}</p>{locate(ref)&&<button className="text-action" onClick={()=>setSelected(ref)}><LocateFixed size={14}/>Locate supporting evidence</button>}</div></details>;});
  return <article className="review-card">
    <div className="review-title"><div><span className="eyebrow">CREATIVE REVIEW · V{review.version}</span><h2>{review.name}</h2></div><span className={`status ${review.status}`}>{(review.status==='draft'?'Uploaded':readable(review.status))}</span></div>
    <div className="review-grid">
      <section className="creative" aria-label="Ad preview">
        {review.image&&!imageFailed?<div className="image-wrap"><img src={review.image} alt={review.name} onError={()=>setImageFailed(true)}/>{visible.map((a,i)=><button key={a.id} className={`annotation ${a.kind} ${selected===a.finding_ref?'active':''}`} style={{left:`${a.box.x*100}%`,top:`${a.box.y*100}%`,width:`${a.box.width*100}%`,height:`${a.box.height*100}%`}} aria-label={`${a.kind==='issue'?'Issue':'Evidence'}: ${a.label}`} onClick={()=>setSelected(a.finding_ref)}><span>{i+1} · {a.label}</span></button>)}</div>:<div className="text-creative"><ImageIcon size={25}/><p>{review.text|| (imageFailed?'The image could not be displayed.':review.fileName?'File attached. No image preview available.':'Paste ad copy or attach an image to start.')}</p></div>}
        <p className="file-caption">{review.fileName ?? 'Text creative'}</p>
        {report&&<p className="small muted">{!live?'Demo coordinates · manually placed':annotations.length?'Regions supplied by the agent':'No region coordinates returned by the backend.'}</p>}
        {review.readiness!==undefined&&<div className="readiness"><div><span>Review readiness {!live&&<small>· sample</small>}</span><strong>{review.readiness}<small>/100</small></strong></div><div className="track"><span style={{width:`${review.readiness}%`}}/></div><p className="small muted">80+ meets the submission threshold. This is not a probability of legal compliance.</p></div>}
      </section>
      <section className="assessment" aria-label="Policy assessment">
        <span className="eyebrow">01 / POLICY ASSESSMENT</span>
        <h3>{report?readable(report.verdict):'Ready when you are'}</h3>
        <p className="summary">{report?.summary ?? 'Run a review to see the applicable policies, evidence and required changes.'}</p>
        {report?.missing_inputs.length? <div className="warning">Missing information: {report.missing_inputs.join(', ')}</div>:null}
        {onlyInternal && <><div className="source-section">Regulatory checks & precedent</div>{passedChecks}<div className="source-section context-source">Current internal legal guidance</div></>}
        {report?.violations.map((v,i)=>{const ref=v.fundamental_key??v.memory_id??`finding-${i}`;return <details key={`${ref}-${i}`} className={`policy issue ${selected===ref?'selected':''}`} open={selected===ref||undefined}><summary><AlertTriangle size={16}/><span>{ref}<small>{v.source==='memory'?'Internal context · Slack':`${v.materiality} finding`}</small></span><ChevronDown size={14}/></summary><div className="policy-body"><h4>Policy requirement</h4><p>{v.evidence.policy_excerpt ?? v.evidence.memory_text ?? (v.evidence.offer_field?`Offer field: ${v.evidence.offer_field}`:'No policy excerpt returned; see the finding rationale below.')}</p><h4>Evidence in the ad</h4><blockquote>{v.quote||'Required content is missing.'}</blockquote><p>{v.explanation}</p>{v.reasoning!==v.explanation&&<p>{v.reasoning}</p>}{locate(ref)&&<button className="text-action" onClick={()=>setSelected(ref)}><LocateFixed size={14}/>Locate on image</button>}</div></details>;})}
        {!onlyInternal && passedChecks}
        {live&&report?.conflicts?.map((c,i)=><details className="policy" key={`conflict-${i}`}><summary><ShieldCheck size={16}/><span>Why this source takes priority</span><ChevronDown size={14}/></summary><div className="policy-body"><p>{c.explanation}</p></div></details>)}
        {report&&<div className="improvements"><span className="eyebrow">02 / REQUIRED IMPROVEMENTS</span>{report.violations.length?<ol>{report.violations.map((v,i)=><li key={i}>{v.fix}</li>)}</ol>:<p><ShieldCheck size={16}/>No required changes identified.</p>}</div>}
        {live&&report?.corrected_copy&&<details className="confidence"><summary>Suggested revised copy</summary><p>{report.corrected_copy}</p></details>}
        {live&&report&&<details className="confidence"><summary>Evidence confidence: {report.confidence.score}/100 · {report.confidence.band}</summary><p>This measures evidence strength, not readiness or risk.</p>{report.confidence.reasons.map((r,i)=><p key={i}>{r}</p>)}</details>}
      </section>
    </div>
  </article>;
}
