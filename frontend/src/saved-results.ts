import data from './codex-results.json';
import {demoReview} from './demo';
import {normalizeReport} from './domain';
import type {Report,Review} from './types';

export function savedReview(id: 'hockey'|'bonus'|'breaks'): Review {
  const fixture=demoReview(id);
  const result=data.results.find(r=>r.file===fixture.fileName);
  if(!result)return fixture;
  return {...fixture,readiness:undefined,report:normalizeReport(result.report as unknown as Report),
    savedResult:{model:data.assessment_model,generatedAt:data.generated_at,claudeDecision:result.claude_decision,seconds:result.seconds},
    trail:[{at:data.generated_at,text:`Saved Codex assessment using seeded policies and memories. Claude baseline: ${result.claude_decision}. No Atlas records changed.`}]};
}
