import type {AdContext, Campaign, ChatResult, CheckResult, FullCampaign, Message, Offer, Session} from './types';
export class ApiError extends Error {constructor(public status: number, message: string) {super(message);}}
export function normalizeBase(raw: string): string {
  const url = new URL(raw.trim());
  if (!['http:','https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) throw new Error('Enter an HTTP or HTTPS backend address without credentials, queries or fragments.');
  if (url.protocol === 'http:' && !['localhost','127.0.0.1','[::1]'].includes(url.hostname)) throw new Error('Use HTTPS for a remote backend. HTTP is supported for localhost only.');
  return url.href.replace(/\/$/,'');
}
export class Backend {
  readonly base: string;
  constructor(base: string, private token = '', private transport: typeof fetch = (input,init)=>fetch(input,init)) {this.base = normalizeBase(base);}
  async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    if (!path.startsWith('/') || path.startsWith('//') || path.includes('://')) throw new Error('Invalid API path.');
    const headers = new Headers(init.headers);
    if (this.token) headers.set('Authorization',`Bearer ${this.token}`);
    if (typeof init.body === 'string') headers.set('Content-Type','application/json');
    let response: Response;
    try {response = await this.transport(this.base + path,{...init,headers,redirect:'error'});}
    catch(error) {if (error instanceof Error && error.name === 'AbortError') throw error;throw new ApiError(0,'Cannot reach FastAPI. Check the backend URL, server, HTTPS and CORS settings.');}
    if (!response.ok) {
      const data = await response.json().catch(()=>({}));
      const detail = data.message ?? data.detail;
      const message = typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map(d=>d.msg ?? 'Invalid request').join('; ') : `Request failed (${response.status}).`;
      throw new ApiError(response.status,message);
    }
    return response.json() as Promise<T>;
  }
  private post<T>(path: string, body: unknown, signal?: AbortSignal) {return this.request<T>(path,{method:'POST',body:JSON.stringify(body),signal});}
  login(email: string,password: string) {return this.post<Session>('/auth/login',{email,password});}
  offers() {return this.request<Offer[]>('/offers');}
  chatHistory(thread: string) {return this.request<{messages: Message[];retained_turns: number}>(`/chat/${encodeURIComponent(thread)}`);}
  campaigns() {return this.request<Campaign[]>('/campaigns');}
  campaign(id: string) {return this.request<FullCampaign>(`/campaigns/${encodeURIComponent(id)}`);}
  upload(file: File,signal?: AbortSignal) {const body=new FormData();body.append('file',file);return this.request<{file_id: string; type: string}>('/assets',{method:'POST',body,signal});}
  check(input: AdContext & {text?: string; file_id?: string; assessment_key?: string; save: boolean; use_memory: boolean; run_id: string},signal?: AbortSignal) {return this.post<CheckResult>('/compliance/check',input,signal);}
  chat(input: {thread_id: string; run_id: string; message: string; ad?: AdContext & {text?: string}; use_memory: boolean},signal?: AbortSignal) {return this.post<ChatResult>('/chat',input,signal);}
  decision(id: string,decision: 'approve'|'reject',feedback: string) {return this.post<Campaign>(`/campaigns/${encodeURIComponent(id)}/${decision}`,{feedback});}
  stop(id: string) {return this.post<{stop_requested: boolean}>(`/runs/${encodeURIComponent(id)}/stop`,{});}
  async asset(fileId: string): Promise<string> {
    const response=await this.transport(`${this.base}/assets/${encodeURIComponent(fileId)}`,{headers:{Authorization:`Bearer ${this.token}`},redirect:'error'});
    if(!response.ok) throw new ApiError(response.status,'Could not load the protected image.');
    const blob=await response.blob();if(!blob.type.startsWith('image/'))throw new Error('The stored asset is not an image.');
    return URL.createObjectURL(blob);
  }
}
