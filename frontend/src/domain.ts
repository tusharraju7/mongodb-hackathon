import type {Annotation, Identity, Report, Review, ViewRole} from './types';
export function roleFor(identity: Identity): ViewRole {return identity.role === 'manager' ? 'lawyer' : 'user';}
export function canSubmit(review: Review, acknowledged: boolean): boolean {
  return review.status === 'draft' && !!review.report && !review.report.missing_inputs.length && (!needsAcknowledgement(review) || acknowledged);
}
export function needsAcknowledgement(review: Review): boolean {return !!review.report && (review.report.verdict !== 'pass' || (review.readiness !== undefined && review.readiness < 80));}
export function validAnnotation(a: Annotation): boolean {
  if (!a || typeof a.id !== 'string' || typeof a.finding_ref !== 'string' || typeof a.label !== 'string' || !['issue','evidence'].includes(a.kind) || !a.box) return false;
  const {x,y,width,height}=a.box;
  return [x,y,width,height].every(Number.isFinite) && x>=0 && y>=0 && width>0 && height>0 && x+width<=1.000001 && y+height<=1.000001;
}
export function canApprove(review: Review, role: ViewRole): boolean {return role === 'lawyer' && review.status === 'pending_review' && review.report?.verdict === 'pass';}
export function normalizeReport(value: Partial<Report> | undefined): Report | undefined {
  if (!value || !['pass','blocked','needs_changes'].includes(value.verdict ?? '')) return undefined;
  const score=value.readiness_score;
  return {decision:value.decision,prompt_version:value.prompt_version,channel_class:value.channel_class,conflicts:value.conflicts??[],verdict: value.verdict!, summary: value.summary ?? 'Assessment returned by the backend.', route: value.route ?? 'human_review', route_reason: value.route_reason ?? '', confidence: value.confidence ?? {score: 0, band: 'unknown', reasons: []}, violations: value.violations ?? [], passed_checks: value.passed_checks ?? [], missing_inputs: value.missing_inputs ?? [], checked_fundamentals: value.checked_fundamentals ?? [], corrected_copy: value.corrected_copy ?? null, memories_used: value.memories_used ?? [], cached: value.cached ?? false, annotations:(value.annotations ?? []).filter(validAnnotation), readiness_score:score && Number.isFinite(score.value) && score.value>=0 && score.value<=100 && score.scale===100 && typeof score.rubric_version==='string' ? score : undefined};
}
export function validateFile(file: Pick<File,'type' | 'size'>, live: boolean): string | undefined {
  if (file.size > 20 * 1024 * 1024) return 'Choose a file smaller than 20 MB.';
  if (live && !['image/png','image/jpeg','image/webp','image/gif'].includes(file.type)) return 'Live review supports PNG, JPEG, WebP and GIF images here. PDF and video analysis need backend support.';
  if (!live && !['image/png','image/jpeg','image/webp','image/gif','application/pdf','video/mp4','video/webm'].includes(file.type)) return 'Choose an image, PDF, MP4 or WebM file.';
}
export const readable = (text: string) => text.replaceAll('_',' ');
export const detailText = (value: unknown): string => typeof value === 'string' ? value : JSON.stringify(value ?? 'No further detail supplied.');
export function makeId(): string {return globalThis.crypto?.randomUUID?.() ?? `gl-${Date.now()}-${Math.random().toString(36).slice(2)}`;}

export function demoReply(message: string,review: Review): string {
  if(!review.report)return 'Open a sample ad from the sidebar to explore a policy review. New uploads are preview-only in this demo.';
  if(/current review status/i.test(message))return `Current status: ${readable(review.status)}.`;
  if(/readiness score/i.test(message))return review.readiness===undefined?'No readiness score is available.':`Demo readiness: ${review.readiness}/100. The suggested submission threshold is 80. This is an illustrative score, not a probability of legal compliance.`;
  if(/checks passed/i.test(message))return review.report.passed_checks.map(c=>`${c.check}: ${c.detail}`).join('\n')||'No passed checks are recorded.';
  if(/internal memory/i.test(message))return review.report.violations.filter(v=>v.source==='memory').map(v=>`${v.memory_id}: ${v.explanation}`).join('\n')||'No internal-memory finding is recorded for this sample.';
  if(/fix first/i.test(message)){const v=review.report.violations[0];return v?`${v.fundamental_key??v.memory_id}: ${v.fix}`:'No required changes are recorded for this sample.';}
  if(/history|past|previous|trail/i.test(message))return review.trail.map(e=>`${e.at}: ${e.text}`).join('\n');
  if(/improv|rewrite|fix|chang/i.test(message))return review.report?.violations.length ? review.report.violations.map(v=>`${v.fundamental_key??v.memory_id}: ${v.fix}`).join('\n\n') : 'No required creative changes are identified in this sample. Confirm placement, current odds and disclosure legibility before publication.';
  if(/why|policy|evidence|risk|pass|score|reject|slack|memory|context/i.test(message))return `${review.report?.summary ?? 'This upload has not been analysed.'}\n\n${review.report?.violations.map(v=>`${v.fundamental_key??v.memory_id}: “${v.quote}” — ${v.explanation} ${v.evidence.memory_text??''}`).join('\n') || review.report?.passed_checks.map(c=>`${c.check}: ${c.detail}`).join('\n') || ''}\n\n${review.savedResult?'This answer summarizes the saved Codex assessment. No new model call was made.':'Demo readiness is an illustrative UI value, not a probability or a live model score.'}`;
  return 'This is a local demo with scripted responses. Ask why this ad passes, what needs changing, or to show its history. Connect FastAPI for real agent responses.';
}


const promptGroups = [
  ['Explain the policy evidence for this ad.', 'What needs changing?', 'Show review history'],
  ['Which finding should I fix first?', 'Explain the readiness score.', 'What is the current review status?'],
  ['What does internal memory say?', 'Which policy checks passed?', 'Summarize the required improvements.'],
];
export function suggestedPrompts(review: Review): string[] {
  const used=new Set(review.messages.filter(m=>m.role==='user').map(m=>m.text));
  // Advance the whole row after a selection. Never recycle earlier groups.
  let group=0;
  for(let i=0;i<promptGroups.length;i++)if(promptGroups[i].some(p=>used.has(p)))group=i+1;
  return promptGroups.slice(group).flat().filter(p=>!used.has(p)).slice(0,3);
}

export function projectCounts(items: {id:string;status:string}[]) {
  const projects=[...new Map(items.map(p=>[p.id,p])).values()];
  const pending=projects.filter(p=>p.status==='pending_review').length;
  const approved=projects.filter(p=>p.status==='approved'||p.status==='released').length;
  const rejected=projects.filter(p=>p.status==='rejected').length;
  return {submitted:pending+approved+rejected,pending,approved,rejected};
}
