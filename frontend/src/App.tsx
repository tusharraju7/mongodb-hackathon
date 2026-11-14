import {useEffect, useRef, useState} from 'react';
import {ArrowUp, Check, ChevronDown, History, LogOut, MessageSquare, Paperclip, Plus, Scale, Settings2, ShieldCheck, Sparkles, UserRound, X} from 'lucide-react';
import {Backend, ApiError} from './api';
import {projectCounts,suggestedPrompts,demoReply,canApprove, canSubmit, makeId, needsAcknowledgement, normalizeReport, readable, roleFor, validateFile} from './domain';
import {savedReview as demoReview} from './saved-results';
import {demoImages} from './demo';
import {demoCredentials,authenticateDemo, type DemoIdentity} from './demo-auth';
import {ReviewCard} from './ReviewCard';
import {MemoryChangeCard} from './MemoryChangeCard';
import type {AdContext, Campaign, MemoryChange, Mode, Offer, Report, Review, Session, ViewRole} from './types';

const STORAGE='greenlight-demo-v1';
// Version 3 replaces illustrative assessments with saved Codex results.
const DEMO_STATE_VERSION=3;
const initialContext: AdContext={name:'Untitled creative',product:'sportsbook',region:'CA-ON',channel:'Instagram (paid social)',language:'en'};
function fresh(): Review {return {key:makeId(),name:'Untitled creative',text:'',version:1,status:'draft',trail:[],messages:[]};}
function loadDemos(): Review[] {
  const defaults=[demoReview('hockey'),demoReview('bonus'),demoReview('breaks')];
  try {
    const saved=JSON.parse(localStorage.getItem(STORAGE)??'null');
    if(saved?.version!==DEMO_STATE_VERSION||!Array.isArray(saved.records))return defaults;
    const restored=defaults.map(r=>{const v=saved.records.find((v: Review)=>v.demoId===r.demoId);return v?{...r,status:v.status,trail:v.trail??[],chats:v.chats??{},messages:[]}:r;});
    return [...restored,...saved.records.filter((v: Review)=>!v.demoId&&v.key&&v.fileName).map((v: Review)=>({...v,messages:[],chats:v.chats??{}}))];
  } catch{return defaults;}
}
const time=()=>new Date().toLocaleString();
const chatDate=(stamp: string)=>new Date(stamp).toLocaleDateString(undefined,{year:'numeric',month:'short',day:'numeric'});
const chatTime=(stamp: string)=>new Date(stamp).toLocaleTimeString(undefined,{hour:'numeric',minute:'2-digit'});
const chatStarted=(stamp: string)=>`${chatDate(stamp)} · ${chatTime(stamp)}`;
const message=(role: 'user'|'assistant'|'lawyer',text: string)=>({id:makeId(),role,text,createdAt:new Date().toISOString()});
export default function App() {
  const [mode,setMode]=useState<Mode>('live');
  const [role,setRole]=useState<ViewRole>('user');
  const [entered,setEntered]=useState(false);
  const [session,setSession]=useState<Session>();
  const [demoIdentity,setDemoIdentity]=useState<DemoIdentity>();
  const [base,setBase]=useState('http://127.0.0.1:3000/api');
  const [email,setEmail]=useState('');
  const [password,setPassword]=useState('');
  useEffect(()=>{
    if(mode==='live'&&!entered){setEmail(role==='lawyer'?'ethan.cho@northplay.test':'amira.haddad@northplay.test');setPassword('');}
    if(mode==='demo'&&!entered){const account=demoCredentials(role);setEmail(account.username);setPassword(account.password);setError('');}
  },[mode,role,entered]);
  const [records,setRecords]=useState<Review[]>(loadDemos);
  const [active,setActive]=useState('demo-hockey');
  const [offers,setOffers]=useState<Offer[]>([]);
  const [context,setContext]=useState<AdContext>(initialContext);
  const [file,setFile]=useState<File>();
  const [fileId,setFileId]=useState<string>();
  const [question,setQuestion]=useState('');
  const [feedback,setFeedback]=useState('');
  const [memoryChange,setMemoryChange]=useState<MemoryChange>();
  const [ack,setAck]=useState(false);
  const [busy,setBusy]=useState('');
  const [error,setError]=useState('');
  const [notice,setNotice]=useState('');
  const [history,setHistory]=useState(false);
  const [library,setLibrary]=useState<Campaign[]>([]);
  const [thread,setThread]=useState(makeId);
  const running=useRef<{id: string; controller: AbortController}|undefined>(undefined);
  const uploadFiles=useRef(new Map<string,File>());
  const uploadIds=useRef(new Map<string,string>());
  const contexts=useRef(new Map<string,AdContext>());
  const fileInput=useRef<HTMLInputElement>(null);
  const urls=useRef<string[]>([]);
  const project=records.find(r=>r.key===active)??records[0];
  const review=project?{...project,messages:project.chats?.[role]??[]}:undefined;
  const live=mode==='live';
  const counts=projectCounts(live?[...library,...records.filter(r=>r.campaignId).map(r=>({id:r.campaignId!,status:r.status}))]:records.map(r=>({id:r.key,status:r.status})));
  const empty=!review?.report&&!review?.fileName&&!review?.text&&!review?.messages.length;
  const backend=()=>new Backend(base,session?.token);
  const update=(fn: (r: Review)=>Review,key=active)=>setRecords(all=>all.map(r=>{if(r.key!==key)return r;const next=fn({...r,messages:r.chats?.[role]??[]});return {...next,messages:[],chats:{...r.chats,[role]:next.messages}};}));
  useEffect(()=>{if(mode==='demo') {try {localStorage.setItem(STORAGE,JSON.stringify({version:DEMO_STATE_VERSION,records:records.filter(r=>r.demoId||r.fileName).map(r=>r.demoId?{demoId:r.demoId,status:r.status,chats:r.chats,trail:r.trail}:r)}));}catch{setNotice('Browser storage is full. New uploads remain available until this page closes.');}}},[records,mode]);
  useEffect(()=>()=>{urls.current.forEach(u=>URL.revokeObjectURL(u));running.current?.controller.abort();},[]);
  function fail(e: unknown) {setError(e instanceof Error?e.message:'Something went wrong.');if(e instanceof ApiError&&e.status===401){setSession(undefined);setEntered(false);}}
  async function signIn() {
    setError('');setNotice('');
    if(!live){
      try {
        const identity=authenticateDemo(email,password,role);
        setDemoIdentity(identity);setRole(identity.role);setPassword('');
        if(identity.role==='user')addNew();
        setEntered(true);
      }catch(e){setPassword('');fail(e);}
      return;
    }
    if(location.protocol==='file:'){setError('For live mode, serve the app with npm run dev or npm run preview. The HTML file can be opened directly in demo mode.');return;}
    setBusy('Signing in');
    try {
      const client=new Backend(base);const result=await client.login(email,password);setPassword('');
      const actual=roleFor(result.user);
      if(role!==actual)throw new Error(`This account has the ${actual==='lawyer'?'Lawyer / manager':'User'} role. Choose that role to continue.`);
      setSession(result);const r=fresh();setRecords([r]);setActive(r.key);setContext(initialContext);setFile(undefined);setFileId(undefined);setEntered(true);
      try {const authorized=new Backend(base,result.token);const cs=await authorized.campaigns();setLibrary(cs);if(cs.length)await openCampaign((cs.find(c=>c.name.startsWith('NP-H'))??cs[0]).id,authorized);}catch(e){setNotice(`Signed in. Could not load project history: ${e instanceof Error?e.message:'Try again.'}`);}
    }catch(e){setPassword('');fail(e);}finally{setBusy('');}
  }
  function logout() {setMemoryChange(undefined);setEntered(false);setDemoIdentity(undefined);setEmail('');setAck(false);setHistory(false);setNotice('');setSession(undefined);setPassword('');setError('');setFile(undefined);setFileId(undefined);setQuestion('');setFeedback('');setLibrary([]);setOffers([]);if(live){uploadFiles.current.clear();uploadIds.current.clear();contexts.current.clear();urls.current.forEach(u=>URL.revokeObjectURL(u));urls.current=[];}setThread(makeId());if(live){const r=fresh();setRecords([r]);setActive(r.key);}else{const rs=records.filter(r=>r.demoId||r.fileName);setRecords(rs);setActive(rs[0]?.key??'demo-hockey');}}
  function changeMode(next: Mode) {setMode(next);setDemoIdentity(undefined);setEmail('');setError('');setNotice('');setSession(undefined);setPassword('');setFile(undefined);setFileId(undefined);const rs=next==='demo'?loadDemos():[fresh()];setRecords(rs);setActive(rs[0].key);setContext(initialContext);}
  function select(key: string) {setMemoryChange(undefined);contexts.current.set(active,context);setContext(contexts.current.get(key)??initialContext);setActive(key);setAck(false);setFeedback('');setFile(uploadFiles.current.get(key));setFileId(uploadIds.current.get(key));setError('');setNotice('');setHistory(false);setThread(makeId());}
  function resetDemo() {
    if(live||busy)return;
    const defaults=[demoReview('hockey'),demoReview('bonus'),demoReview('breaks')];
    setRecords(defaults);setActive(defaults[0].key);setContext(initialContext);
    uploadFiles.current.clear();uploadIds.current.clear();contexts.current.clear();
    urls.current.forEach(u=>URL.revokeObjectURL(u));urls.current=[];
    setFile(undefined);setFileId(undefined);setAck(false);setFeedback('');setQuestion('');setHistory(false);setError('');setNotice('All demo projects reset to default.');setThread(makeId());
  }
  function addNew() {const r=fresh();setRecords(all=>[...all,r]);select(r.key);setContext(initialContext);}
  async function attach(f?: File) {
    if(!f)return;const problem=validateFile(f,live);if(problem){setError(problem);return;}
    const r=fresh();r.name=f.name;r.fileName=f.name;
    if(f.type.startsWith('image/')) {
      if(live){r.image=URL.createObjectURL(f);urls.current.push(r.image);}
      else {try{r.image=await new Promise<string>((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result));reader.onerror=()=>reject(new Error('Could not read image.'));reader.readAsDataURL(f);});}catch(e){fail(e);return;}}
    }
    setRecords(all=>[...all,r]);uploadFiles.current.set(r.key,f);select(r.key);setFile(f);setContext({...initialContext,name:f.name});
    if(!live)setNotice('Preview only. Open a sample ad for demo findings.');
  }
  async function loadExample(id: 'hockey'|'bonus'|'breaks') {
    try {const item=demoReview(id);const response=await fetch(demoImages[id]);const blob=await response.blob();await attach(new File([blob],item.fileName!,{type:'image/png'}));}
    catch(e){fail(e);}
  }
  async function recheckProject() {
    if(!review?.campaignId||!session)return;
    setBusy('Reviewing stored project');setError('');
    try {await backend().check({...context,campaign_id:review.campaignId,save:true,use_memory:true,run_id:makeId()});await openCampaign(review.campaignId);await refreshHistory();}
    catch(e){fail(e);}finally{setBusy('');}
  }
  async function runReview(save=false) {
    if(!live||!session||!review)return;
    if(!context.channel.trim()){setError('Enter the ad placement or channel.');return;}
    if(!file&&!fileId&&!review.text?.trim()&&!review.campaignId){setError('Attach an image or paste the ad copy first.');return;}
    if(save&&!canSubmit(review,ack))return;
    if(save&&!review.assessmentKey){setError("Run a current assessment before submitting.");return;}
    setError('');setNotice('');setBusy(save?'Submitting for legal review':'Reading the ad and assessing policies');
    const id=makeId(),controller=new AbortController();running.current={id,controller};
    try {
      const api=backend();let fid=fileId;
      if(file&&!fid){setBusy('Uploading image');fid=(await api.upload(file,controller.signal)).file_id;setFileId(fid);uploadIds.current.set(active,fid);setBusy('Assessing applicable policies');}
      const result=await api.check({...context,name:review.name,campaign_id:review.campaignId,text:review.text||undefined,file_id:fid,assessment_key:save?review.assessmentKey:undefined,save,use_memory:true,run_id:id},controller.signal);
      const report=normalizeReport(result);if(!report)throw new Error('The backend did not return an assessment. Check the ad and required context.');
      update(r=>({...r,report,assessmentSource:'live',assessmentKey:result.assessment_key,readiness:report.readiness_score?.value,campaignId:result.campaign?.id??r.campaignId,version:result.campaign?.version??r.version,status:result.campaign?.status??r.status,trail:[...r.trail,{at:time(),text:`${save?'Submitted existing assessment':'Assessed'}: ${readable(report.verdict)}. Run ${id}.`}],messages:[...r.messages,message('assistant',save?result.campaign?'Submitted for legal review using the existing assessment. The server verified that its inputs and evidence are still current.':'The backend did not file this ad. Resolve the missing information before submitting.':report.summary)]}));
      if(save)setAck(false);
    }catch(e){fail(e);}finally{setBusy('');running.current=undefined;}
  }
  async function send(text=question) {
    const q=text.trim();if(!q||!review||busy)return;setQuestion('');setError('');update(r=>({...r,messages:[...r.messages,message('user',q)]}));
    if(!live){update(r=>({...r,messages:[...r.messages,message('assistant',demoReply(q,r))]}));return;}
    if(!session)return;if((file||fileId)&&!review.report){await runReview();return;}setBusy('Agent is working');const id=makeId(),controller=new AbortController();running.current={id,controller};
    try {
      // Do not send ad.text on follow-up: that field forces a fresh review in the current backend.
      const result=await backend().chat({thread_id:review.campaignId?`project-${review.campaignId}`:thread,ad:review.campaignId?{...context,campaign_id:review.campaignId}:undefined,run_id:id,message:review.campaignId?`Regarding campaign ${review.campaignId}: ${q}`:`${q}\n\nCurrent ad context: ${review.name}. ${review.report?.summary??''} ${review.text??''}`,use_memory:true},controller.signal);
      let report: Report|undefined,campaign: Campaign|undefined;
      for(const c of result.cards){if(c.type==='compliance_report')report=normalizeReport(c.data as Report);if(c.type==='campaign')campaign=c.data as Campaign;if(c.type==='memory_change')setMemoryChange(c.data as MemoryChange);}
      update(r=>({...r,...(report?{report,readiness:report.readiness_score?.value}:{}),...(campaign&&campaign.id===r.campaignId?{status:campaign.status,version:campaign.version}:{}),messages:[...r.messages,message('assistant',result.reply)],trail:[...r.trail,{at:time(),text:`Assessment activity · ${result.status} · Run ${id}` }]}));
    }catch(e){fail(e);}finally{setBusy('');running.current=undefined;}
  }
  async function confirmMemory(reason: string,password: string) {
    if(!memoryChange||!session)return;
    setBusy('Saving memory change');setError('');
    try {await backend().applyMemoryChange(memoryChange,reason,password);setMemoryChange(undefined);update(r=>({...r,messages:[...r.messages,message('assistant','Memory updated. Future reviews will retrieve the current knowledge. Existing reports remain historical until reviewed again.')]}));}
    catch(e){fail(e);}finally{setBusy('');}
  }
  async function submit() {
    if(!entered||role!=='user'||(!live&&demoIdentity?.role!=='user')||!review||!canSubmit(review,ack))return;
    if(live){await runReview(true);return;}
    update(r=>({...r,status:'pending_review',trail:[...r.trail,{at:time(),text:needsAcknowledgement(r)?'Submitted with unresolved findings acknowledged (demo).':'Submitted for legal review (demo).'}],messages:[...r.messages,message('assistant','Submitted for legal review in this demo. Sign out and sign in with the lawyer demo account to record a decision. This does not publish the ad.')]}));setAck(false);
  }
  async function decide(action: 'approve'|'reject') {
    if(!entered||!review||role!=='lawyer'||(!live&&demoIdentity?.role!=='lawyer')||(live&&review.status!=='pending_review')||(!live&&(!review.report||['approved','rejected'].includes(review.status))))return;
    if(live&&action==='approve'&&!canApprove(review,role))return;
    
    setError('');setBusy('Saving decision');
    try {
      const status=action==='approve'?'approved':'rejected';
      if(live){if(!review.campaignId)throw new Error('This ad has not been submitted to the backend.');await backend().decision(review.campaignId,action,feedback.trim());}
      update(r=>({...r,status,trail:[...r.trail,{at:time(),text:`${readable(status)}${feedback.trim()?`: ${feedback.trim()}`:''}${live?'':' (demo)'}`}],messages:[...r.messages,message('lawyer',`${action==='approve'?'Approved':'Not approved'}${feedback.trim()?` — ${feedback.trim()}`:''}`)]}));setFeedback('');
    }catch(e){fail(e);}finally{setBusy('');}
  }
  async function openCampaign(id: string, client?: Backend) {
    setBusy('Loading prior review');setError('');
    try {
      const api=client??backend(),c=await api.campaign(id);const report=normalizeReport(c.compliance);
      const r: Review={key:c.id,campaignId:c.id,assessmentSource:c.source==='seed'&&!c.compliance.prompt_version?'team':'live',name:c.name,version:c.version,status:c.status,text:c.text,report,readiness:report?.readiness_score?.value,messages:c.review_feedback?[message('lawyer',c.review_feedback)]:[],trail:(c.history??[]).map(h=>({at:`Version ${h.version}`,text:`${h.status??'Earlier version'} · ${h.compliance?.verdict??'No stored verdict'}. Earlier snapshots may not contain the full analysis.`}))};
      const savedChat=await api.chatHistory(`project-${c.id}`);
      r.chats={[role]:savedChat.messages.map((m,i)=>({...m,id:m.id??`${c.id}-${role}-${i}`}))};
      r.messages=[];
      const asset=c.assets?.find(a=>a.type==='image');
      if(asset){try{r.image=await api.asset(asset.file_id);urls.current.push(r.image);}catch(e){setNotice(e instanceof Error?e.message:'Image unavailable.');}}
      r.trail.push({at:`Version ${c.version}`,text:`Current status: ${readable(c.status)}. ${report?.summary??''}`});
      setRecords(all=>[...all.filter(a=>a.key!==r.key),r]);select(r.key);setContext({name:c.name,product:c.product??'sportsbook',offer_id:c.offer_id,region:c.region??'CA-ON',channel:c.channel??'social',language:c.language??'en',campaign_id:c.id});
    }catch(e){fail(e);}finally{setBusy('');}
  }
  async function refreshHistory() {setBusy('Loading review history');setError('');try{setLibrary(await backend().campaigns());}catch(e){fail(e);}finally{setBusy('');}}
  async function stop() {if(!running.current)return;try{await backend().stop(running.current.id);setNotice('Stop requested. A model call already in progress may finish before the next step stops.');}catch(e){fail(e);}}
  if(!entered)return <div className="login-page"><div className="login-art"><div className="brand"><Sparkles/><strong>greenlight</strong></div><div><span className="eyebrow">POLICY FIRST. CREATIVE FORWARD.</span><h1>A clearer path<br/>from ad to approval.</h1><p>Your creative, the relevant policies, and the next step—together in one conversation.</p></div><div className="login-foot"><ShieldCheck size={18}/>Human judgment, supported by evidence.</div></div><main className="login-form"><span className="eyebrow">WELCOME TO GREENLIGHT</span><h2>Choose your workspace</h2><p className="muted">Review creative with the context that matters.</p><div className="role-picker"><button aria-pressed={role==='user'} onClick={()=>setRole('user')} disabled={!!busy}><UserRound/><strong>User</strong><span>Create, assess and submit</span></button><button aria-pressed={role==='lawyer'} onClick={()=>setRole('lawyer')} disabled={!!busy}><Scale/><strong>Lawyer</strong><span>Review and give feedback</span></button></div><div className="mode-picker"><button aria-pressed={!live} onClick={()=>changeMode('demo')} disabled={!!busy}>Saved demos</button><button aria-pressed={live} onClick={()=>changeMode('live')} disabled={!!busy}>Connect backend</button></div><form onSubmit={e=>{e.preventDefault();void signIn();}}>{live&&<label>FastAPI backend URL<input type="url" value={base} onChange={e=>setBase(e.target.value)} required disabled={!!busy}/></label>}<label>{live?'Email':'Username'}<input type={live?'email':'text'} value={email} onChange={e=>setEmail(e.target.value)} autoComplete="username" autoCapitalize="none" spellCheck={false} required disabled={!!busy}/></label><label>Password<input type="password" value={password} onChange={e=>setPassword(e.target.value)} autoComplete="current-password" required disabled={!!busy}/></label><p className="small muted">Your account determines your role. Sign out to change accounts.</p>{error&&<p role="alert" className="error">{error}</p>}<button className="primary full" disabled={!!busy}>{busy||`Sign in as ${role==='lawyer'?'Lawyer':'User'}`}</button></form><p className="small muted login-disclaimer">{live?'Sign in to upload and assess ads with the live backend.':'Demo credentials are prefilled. These are saved assessments; login is simulated locally.'}</p></main></div>;
  return <div className="app-layout"><aside className="sidebar"><div className="brand"><Sparkles/><strong>greenlight</strong></div><button className="new-chat" onClick={addNew} disabled={!!busy}><Plus size={17}/>New ad conversation</button><section className="project-counts" aria-label="Project counts"><div><strong>{counts.submitted}</strong><span>Submitted</span></div><div><strong>{counts.pending}</strong><span>Pending review</span></div><div><strong>{counts.approved}</strong><span>Approved</span></div><div><strong>{counts.rejected}</strong><span>Rejected</span></div></section><div className="sidebar-label">{live?'THIS SESSION':'PROJECTS'}</div><nav aria-label="Ad conversations">{records.map(r=><button key={r.key} className={r.key===active?'active':''} onClick={()=>select(r.key)} disabled={!!busy}><MessageSquare size={16}/><span>{r.name}<small>{r.status==='draft'?'Uploaded':readable(r.status)}</small>{r.chats?.[role]?.[0]?.createdAt&&<small className="chat-start-preview">{chatStarted(r.chats[role]![0].createdAt!)}</small>}</span></button>)}</nav>{live&&<details className="past-reviews" open><summary><History size={16}/>Project library</summary><button className="text-action" onClick={()=>void refreshHistory()} disabled={!!busy}>Refresh history</button>{library.map(c=><button key={c.id} onClick={()=>void openCampaign(c.id)} disabled={!!busy}>{c.name}<small>{readable(c.status)} · v{c.version}</small></button>)}{!library.length&&<p className="small muted">No saved reviews loaded.</p>}</details>}<div className="sidebar-bottom"><span className="mode-badge">{live?'Connected backend':'Saved results · no new AI calls'}</span><p>{live?session?.user.name||session?.user.email:demoIdentity?.username}</p><button className="text-action" onClick={logout} disabled={!!busy}><LogOut size={15}/>Sign out</button></div></aside>
    <div className="workspace"><header className="topbar"><div><span className="eyebrow">AD REVIEW CONVERSATION</span><h1>{role==='lawyer'?'Lawyer view':'User view'}</h1></div><div className="top-actions">{live&&<button className="text-action" disabled={!!busy} onClick={()=>{setQuestion(role==='lawyer'?'Remember for our team: ':'Remember for me: ');document.getElementById('chat-input')?.focus();}}>Update memory</button>}{!live?<button className="icon-button" aria-label="Reset all demos to default" title="Reset all demos to default" disabled={!!busy} onClick={resetDemo}><History size={19}/></button>:<button className="icon-button" aria-label="Show analysis history" aria-pressed={history} onClick={()=>setHistory(!history)}><History size={19}/></button>}</div></header>
      <main className={`chat-content${empty?' is-empty':''}`}>
        {!empty&&<div className="context-bar"><span>{live?review.assessmentSource==='team'?'Team-provided recorded assessment':'Live backend assessment':'NorthPlay · Ontario · Public social'}</span><span>{live?'Server-enforced permissions':review.savedResult?'Saved Codex result · seeded data':'Illustrative assessment'}</span></div>}
        {live&&role==='user'&&<div className="button-row" aria-label="Upload an example for live review"><button className="secondary" disabled={!!busy} onClick={()=>void loadExample('hockey')}>Use Hockey ad</button><button className="secondary" disabled={!!busy} onClick={()=>void loadExample('bonus')}>Use Bonus ad</button><button className="secondary" disabled={!!busy} onClick={()=>void loadExample('breaks')}>Use Play Smart ad</button></div>}
        {live&&review?.campaignId&&<p className="small muted">{context.region} · {context.channel} · Metadata loaded from the project <button className="text-action" disabled={!!busy} onClick={()=>void recheckProject()}>Review against current policies</button></p>}{live&&!review?.campaignId&&<details className="live-context"><summary><Settings2 size={16}/>Ad context <ChevronDown size={14}/></summary><p className="small muted">NorthPlay · Ontario sportsbook. Choose where the ad will appear.</p><fieldset disabled={!!busy||review?.status!=='draft'||!!review?.report}><div className="context-fields"><label>Ad name<input value={review?.name??context.name} onChange={e=>{const name=e.target.value;setContext(c=>({...c,name}));update(r=>({...r,name}));}}/></label><label>Region<select value={context.region} onChange={e=>setContext(c=>({...c,region:e.target.value}))}><option value="CA-ON">Ontario</option><option value="CA-AB">Alberta</option></select></label><label>Channel<input value={context.channel} onChange={e=>setContext(c=>({...c,channel:e.target.value}))} placeholder="Instagram (paid social)"/></label></div><label>Ad copy (or attach an image)<textarea rows={3} value={review?.text??''} onChange={e=>update(r=>({...r,text:e.target.value}))} placeholder="Paste the exact copy to review…"/></label></fieldset><div className="button-row"><button className="secondary" disabled={!!busy||!!review?.report} onClick={()=>fileInput.current?.click()}><Paperclip size={16}/>Attach image</button><button className="primary" disabled={!!busy||!!review?.report} onClick={()=>void runReview()}>Review ad</button></div></details>}
        {notice&&<p className="notice" role="status">{notice}</p>}{error&&<p className="error" role="alert">{error}</p>}
        {empty&&<section className="empty-conversation"><span className="empty-symbol"><Sparkles size={27}/></span><h2>What would you like to review?</h2><p>Attach an ad or start a conversation.</p></section>}
        {review&&<>{review.report&&<ReviewCard key={`${review.key}-${review.version}-${review.image??''}`} review={review} live={live}/>}
        {live&&!review.report&&(review.fileName||review.text)&&<button className="primary" disabled={!!busy} onClick={()=>void runReview()}>Review uploaded ad</button>}{!review.report&&review.fileName&&<section className="attachment-preview" aria-label="Attached creative">{review.image&&<img src={review.image} alt={review.fileName}/>}<div><Paperclip size={18}/><span>{review.fileName}</span><small>Preview</small></div></section>}{!live&&role==='lawyer'&&(review.report||review.fileName)&&!['approved','rejected'].includes(review.status)&&<section className="demo-decision" aria-label="Demo review decision"><div className="button-row"><button className="primary" disabled={!!busy||!review.report} onClick={()=>void decide('approve')}><Check size={16}/>Approve</button><button className="secondary danger" disabled={!!busy||!review.report} onClick={()=>void decide('reject')}><X size={16}/>Reject</button></div>{!review.report&&<p className="small muted">An assessment is required before a decision. Uploads are preview-only in this demo.</p>}<label>Note (optional)<textarea rows={2} value={feedback} onChange={e=>setFeedback(e.target.value)} disabled={!!busy} placeholder="Add feedback…"/></label></section>}
        {review.report&&(live||role==='user')&&<section className="review-actions" aria-label="Review actions">{role==='user'?review.status==='draft'?<><div><h3>Ready for legal review?</h3><p className="small muted">Submit this creative and its assessment for a human decision.</p></div>{needsAcknowledgement(review)&&<div className="warning"><p>{review.readiness!==undefined?'This creative falls below the recommended readiness threshold.':'This creative has unresolved policy findings.'} You may still request legal review; the findings remain visible to the reviewer.</p><label className="check-label"><input type="checkbox" checked={ack} onChange={e=>setAck(e.target.checked)} disabled={!!busy}/>I acknowledge the unresolved findings and want to submit for review.</label></div>}<button className="primary" disabled={!!busy||!canSubmit(review,ack)} onClick={()=>void submit()}>{needsAcknowledgement(review)&&ack?'Submit anyway':'Submit for legal review'}</button></>:<p className="decision-summary"><ShieldCheck size={18}/>{review.status==='pending_review'?'Awaiting a lawyer’s decision.':`This creative is ${readable(review.status)}.`}</p>:review.status==='pending_review'?<><h3>Your review decision</h3><p className="small muted">Assess the policy evidence before recording your feedback. Approval does not publish the ad.</p><label>Decision note (optional)<textarea rows={3} value={feedback} onChange={e=>setFeedback(e.target.value)} disabled={!!busy} placeholder="Explain the decision and any required changes…"/></label>{!canApprove(review,role)&&<p className="small muted">Approval is unavailable while policy findings remain. This matches the current backend rule.</p>}<div className="button-row"><button className="secondary danger" disabled={!!busy} onClick={()=>void decide('reject')}><X size={16}/>Reject</button><button className="primary" disabled={!!busy||!canApprove(review,role)} onClick={()=>void decide('approve')}><Check size={16}/>Approve</button></div></>:<p className="small muted">{review.status==='draft'?'This ad has not been submitted. The user must request legal review first.':`Decision recorded: ${readable(review.status)}.`}</p>}</section>}
        {history&&<section className="history-panel"><h3><History size={17}/>Analysis history</h3>{review.trail.length?<ol>{review.trail.map((t,i)=><li key={i}><small>{t.at}</small><p>{t.text}</p></li>)}</ol>:<p>No analysis recorded yet.</p>}<p className="small muted">{live?'Shared project versions and decisions. Personal chat retains the latest 6 turns.':'Sample-ad history is saved in this browser. Shared HTML starts with fresh demo data.'}</p></section>}
        {live&&memoryChange&&<MemoryChangeCard key={`${memoryChange.target}-${memoryChange.id??'new'}-${memoryChange.after}`} change={memoryChange} busy={!!busy} onConfirm={confirmMemory} onCancel={()=>setMemoryChange(undefined)}/>}
        <div className="messages" aria-live="polite">{review.messages.length>0&&<p className="conversation-start">{review.messages[0].createdAt?`Conversation started ${chatStarted(review.messages[0].createdAt)}`:'Earlier conversation · start time unavailable'}</p>}{review.messages.map((m,index)=><div key={m.id} className="message-entry">{m.createdAt&&index>0&&(!review.messages[index-1].createdAt||chatDate(m.createdAt)!==chatDate(review.messages[index-1].createdAt!))&&<p className="conversation-date">{chatDate(m.createdAt)}</p>}<div className={m.role==='user'?'user-bubble':'assistant-message'}>{m.role!=='user'&&<strong>{m.role==='lawyer'?'Legal reviewer':'Greenlight'}{!live&&' · demo'}</strong>}<p>{m.text}</p>{m.createdAt&&<time className="message-time" dateTime={m.createdAt} title={chatStarted(m.createdAt)}>{chatTime(m.createdAt)}</time>}</div></div>)}</div></>}
        {busy&&<div className="working" role="status"><span className="working-dot"/>{busy}…{live&&running.current&&<button className="text-action" onClick={()=>void stop()}>Request stop</button>}</div>}
        {review?.report&&suggestedPrompts(review).length>0&&<div className="suggestions">{suggestedPrompts(review).map(prompt=><button key={prompt} onClick={()=>void send(prompt)} disabled={!!busy}>{prompt}</button>)}</div>}
        <form className="chat-form" onSubmit={e=>{e.preventDefault();void send();}}><label className="sr-only" htmlFor="chat-input">Message Greenlight</label><button type="button" className="icon-button" aria-label="Attach a new creative" onClick={()=>fileInput.current?.click()} disabled={!!busy}><Paperclip size={20}/></button><input id="chat-input" value={question} onChange={e=>setQuestion(e.target.value)} placeholder={empty?'Message Greenlight…':'Ask about this review…'} maxLength={4000} disabled={!!busy}/><button className="send-button" aria-label="Send message" disabled={!!busy||!question.trim()}><ArrowUp size={20}/></button></form>
        <input ref={fileInput} type="file" className="sr-only" tabIndex={-1} accept={live?'image/png,image/jpeg,image/webp,image/gif':'image/png,image/jpeg,image/webp,image/gif,application/pdf,video/mp4,video/webm'} onChange={e=>{attach(e.target.files?.[0]);e.target.value='';}}/>
        <p className="chat-footnote">{live?'Responses come from your backend. Final approval remains a human decision.':'Saved results · no new AI calls'}</p>
      </main>
    </div>
  </div>;
}
