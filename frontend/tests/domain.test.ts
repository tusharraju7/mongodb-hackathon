import test from 'node:test';
import assert from 'node:assert/strict';
import {suggestedPrompts,demoReply,canApprove,canSubmit,needsAcknowledgement,normalizeReport,roleFor,validAnnotation,validateFile} from '../src/domain';
import type {Review,Report,Annotation} from '../src/types';
const report: Report={verdict:'pass',summary:'Pass',route:'none',route_reason:'',confidence:{score:97,band:'high',reasons:[]},violations:[],passed_checks:[],missing_inputs:[],checked_fundamentals:[],corrected_copy:null,memories_used:[],cached:false};
const base: Review={key:'test',name:'Test',version:1,status:'draft',report,readiness:92,messages:[],trail:[]};
test('readiness threshold requires explicit acknowledgement below 80',()=>{assert.equal(canSubmit({...base,readiness:80},false),true);assert.equal(canSubmit({...base,readiness:79},false),false);assert.equal(canSubmit({...base,readiness:79},true),true);});
test('high readiness cannot hide a blocking policy finding',()=>{const r={...base,report:{...report,verdict:'blocked' as const}};assert.equal(needsAcknowledgement(r),true);assert.equal(canSubmit(r,false),false);assert.equal(canSubmit(r,true),true);});
test('missing information and already submitted ads cannot be submitted',()=>{assert.equal(canSubmit({...base,report:{...report,missing_inputs:['offer']}},true),false);assert.equal(canSubmit({...base,status:'pending_review'},true),false);assert.equal(canSubmit({...base,report:undefined},true),false);});
test('approval requires lawyer, pending status and a passing verdict',()=>{const pending={...base,status:'pending_review' as const};assert.equal(canApprove(pending,'lawyer'),true);assert.equal(canApprove(pending,'user'),false);assert.equal(canApprove(base,'lawyer'),false);assert.equal(canApprove({...pending,report:{...report,verdict:'blocked'}},'lawyer'),false);});
test('server identity defines access, not a role picker',()=>{assert.equal(roleFor({user_id:'1',email:'x@y.test',name:'',team:'national',role:'marketer'}),'user');assert.equal(roleFor({user_id:'1',email:'x@y.test',name:'',team:'national',role:'manager'}),'lawyer');});
test('evidence confidence is never converted into readiness',()=>{const r=normalizeReport(report);assert.equal(r?.confidence.score,97);assert.equal(r?.readiness_score,undefined);assert.equal(canSubmit({...base,readiness:undefined},false),true);});
test('future annotations are normalized and invalid coordinates discarded',()=>{const good: Annotation={id:'a',finding_ref:'R1',label:'Issue',kind:'issue',box:{x:.1,y:.3,width:.2,height:.1}};assert.equal(validAnnotation(good),true);assert.equal(validAnnotation({...good,box:{...good.box,width:1}}),false);assert.equal(validAnnotation({...good,box:{...good.box,x:-.1}}),false);const r=normalizeReport({...report,annotations:[good,{...good,box:{...good.box,height:NaN}}],readiness_score:{value:75,scale:100,rubric_version:'v1'}});assert.equal(r?.annotations?.length,1);assert.equal(r?.readiness_score?.value,75);assert.equal(normalizeReport({...report,readiness_score:{value:101,scale:100,rubric_version:'v1'}})?.readiness_score,undefined);});
test('unsupported media and oversized images are blocked before upload',()=>{assert.match(validateFile({type:'application/pdf',size:1},true)??'',/backend support/);assert.equal(validateFile({type:'application/pdf',size:1},false),undefined);assert.match(validateFile({type:'image/png',size:21*1024*1024},true)??'',/20 MB/);assert.equal(validateFile({type:'image/png',size:100},true),undefined);});

test('the changing suggestion returns the selected ad’s specific fix',()=>{const r={...base,report:{...report,violations:[{source:'memory',memory_id:'SLACK-2026-10-30-JAKE',materiality:'material',quote:'Jake',explanation:'Rights ended.',reasoning:'Internal guidance.',evidence:{memory_text:'Legal decision'},fix:'Remove the attributed quote.',confidence:report.confidence}]}};assert.match(demoReply('What needs changing?',r),/Remove the attributed quote/);assert.match(demoReply('Explain the policy evidence',r),/SLACK-2026-10-30-JAKE/);});

test('suggestions advance the whole row without repeating earlier prompts',()=>{
  const initial=suggestedPrompts(base);
  let r={...base,messages:[{id:'p1',role:'user' as const,text:initial[0]}]};
  const next=suggestedPrompts(r);
  assert.equal(next.length,3);
  assert.ok(next.every(p=>!initial.includes(p)));
  r={...r,messages:[...r.messages,{id:'p2',role:'user',text:next[0]}]};
  const last=suggestedPrompts(r);
  assert.ok(last.every(p=>!initial.includes(p)&&!next.includes(p)));
  r={...r,messages:[...r.messages,{id:'p3',role:'user',text:last[0]}]};
  assert.deepEqual(suggestedPrompts(r),[]);
  assert.deepEqual(suggestedPrompts(base),initial);
});
