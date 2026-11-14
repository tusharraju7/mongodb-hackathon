"""Print configuration presence and service availability, never credential values.
Run with --voyage for one small billable embedding request. No balance claims.
"""
import argparse
import json
import os
from app.core.config import get_settings

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--voyage',action='store_true')
    args=parser.parse_args()
    s=get_settings()
    result={'configured':{k:bool(os.getenv(k)) for k in ['OPENAI_API_KEY','MONGODB_URI','VOYAGE_API_KEY','JWT_SECRET','SEED_PASSWORD']},'models':{'judge':s.llm_model,'fast':s.llm_fast_model},'balances':'Not available from application credentials; check provider billing dashboards.'}
    try:
        from app.core.db import get_db
        db=get_db()
        db.command('ping')
        result['mongodb']={'connection':'reachable','counts':{name:db[name].count_documents({}) for name in ['users','fundamentals','campaigns','memories','policies','slack_messages','strategy_docs','runs']}}
    except Exception as e:result['mongodb']={'connection':'failed','error_type':type(e).__name__}
    if args.voyage:
        try:
            import voyageai
            response=voyageai.Client(api_key=s.voyage_api_key,max_retries=0,timeout=20).embed(['NorthPlay connectivity check'],model=s.voyage_model,input_type='query')
            result['voyage']={'connection':'reachable','dimensions':len(response.embeddings[0]),'tokens':response.total_tokens}
        except Exception as e:result['voyage']={'connection':'failed','error_type':type(e).__name__}
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
