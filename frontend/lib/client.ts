export const phases = ["VERIFY_ID", "RESOLVE_INTENT", "PROCESS_CASE", "POST_PROCESS"] as const;
export type Phase = (typeof phases)[number];
type SessionStatus = "active" | "handoff" | "completed";
type Claim = { case_id: string; type: string; status: string; created_at: string };
export type Summary = {revision:string; claim:Claim|null; topics:string[]; documents:string[];
  recipient:string|null; disposition:"pending"|"simulated"|"declined"; actions:("send"|"skip")[]};
export type Workspace = {session_id:string; phase:Phase; status:SessionStatus; verification:string;
  claim:Claim|null; summary:Summary|null; handoff:string|null; human_offer:boolean; provider:string; demo:boolean;
  transcript:{message_id:string;response:string}[]};
export type Reply = {session_id:string; message_id:string; phase:Phase; session_status:SessionStatus;
  response:string; next_expected_action:string};
type Event = {event_id:string; timestamp:string; event_type:string; phase:Phase;
  action:string|null; decision:string|null; reason:string|null};
export type Diagnostics = {events:Event[]; matched:number; required:number; intent:string|null;
  secondary_intents:string[];
  emotion:string|null; scope_count:number; refusals:number; pending:string[];
  hints:Record<string,string|number|null>; provenance:Record<string,number>; origin_phases:Record<string,Phase>};

type Row = Record<string, unknown>;
const obj = (value:unknown):value is Row => typeof value === "object" && value !== null && !Array.isArray(value);
const str = (value:unknown):value is string => typeof value === "string";
const strings = (value:unknown):value is string[] => Array.isArray(value) && value.every(str);
const nullable = (value:unknown):value is string|null => value === null || str(value);
const phase = (value:unknown):value is Phase => str(value) && phases.some(item=>item===value);
const status = (value:unknown):value is SessionStatus => value==="active"||value==="handoff"||value==="completed";
const claim = (value:unknown):value is Claim => obj(value) && [value.case_id,value.type,value.status,value.created_at].every(str);
const summary = (value:unknown):value is Summary => obj(value) && str(value.revision) &&
  (value.claim===null||claim(value.claim)) && strings(value.topics) && strings(value.documents) &&
  nullable(value.recipient) && ["pending","simulated","declined"].some(v=>v===value.disposition)
  && Array.isArray(value.actions) && value.actions.every(v=>v==="send"||v==="skip");

export const isWorkspace = (value:unknown): value is Workspace => obj(value) && str(value.session_id) &&
  phase(value.phase) && status(value.status) && str(value.verification) &&
  (value.claim===null||claim(value.claim)) && (value.summary===null||summary(value.summary)) &&
  nullable(value.handoff) && typeof value.human_offer==="boolean" && str(value.provider) && typeof value.demo==="boolean" &&
  Array.isArray(value.transcript) && value.transcript.every(v=>obj(v) && str(v.message_id) && str(v.response)) &&
  ((value.claim===null && value.summary===null) || value.verification==="verified");
export const isReply = (value:unknown): value is Reply => obj(value) && phase(value.phase) &&
  status(value.session_status) && [value.session_id,value.message_id,value.response,value.next_expected_action].every(str);
export const isDiagnostics = (value:unknown): value is Diagnostics => obj(value) &&
  Array.isArray(value.events) && value.events.every(e=>obj(e) && phase(e.phase) &&
    [e.event_id,e.timestamp,e.event_type].every(str) && [e.action,e.decision,e.reason].every(nullable)) &&
  [value.matched,value.required,value.scope_count,value.refusals].every(v=>typeof v==="number") &&
  nullable(value.intent) && nullable(value.emotion) && strings(value.pending) &&
  strings(value.secondary_intents) &&
  obj(value.hints) && Object.values(value.hints).every(v=>nullable(v)||typeof v==="number") &&
  obj(value.provenance) && Object.values(value.provenance).every(v=>typeof v==="number") &&
  obj(value.origin_phases) && Object.values(value.origin_phases).every(phase);

export class RequestError extends Error {
  readonly status:number;
  constructor(status:number) { super("Request failed"); this.status=status; }
}

export async function request<T>(action:string, validate:(value:unknown)=>value is T, body?:unknown,
                                 signal?:AbortSignal):Promise<T> {
  let response:Response;
  try {
    const timeout = AbortSignal.timeout(38000);
    response = await fetch("/gateway/" + action, {
      method: body===undefined ? "GET" : "POST", cache:"no-store",
      headers: body===undefined ? undefined : {"Content-Type":"application/json"},
      body: body===undefined ? undefined : JSON.stringify(body),
      signal: signal ? AbortSignal.any([signal,timeout]) : timeout,
    });
  } catch { throw new RequestError(503); }
  if (!response.ok) throw new RequestError(response.status);
  const data:unknown = await response.json().catch(()=>null);
  if (!validate(data)) throw new RequestError(502);
  return data;
}

export function userError(error:unknown) {
  const status = error instanceof RequestError ? error.status : 503;
  if(status===404) return "Your session is unavailable. Start a new conversation if it expired.";
  if(status===409) return "This request conflicts with the current session. The panel will refresh.";
  if(status===413||status===415||status===422) return "Check your message format and length, then try again.";
  if(status===429) return "Too many requests. Wait a moment and try again.";
  return "The support service could not be reached. Please try again.";
}

export function displayMessage(text:string, current:Phase) {
  if (current==="VERIFY_ID" || /\b(?:ssn|birthday|dob|my name is|social security|policy pol-)\b|@|\b\d{4,}\b/i.test(text)) {
    return "Message submitted securely.";
  }
  return text;
}
export function validMessage(text:string) { return text.trim().length>0 && text.trim().length<=4000; }
export function makeMessage(text:string) { return {message_id:crypto.randomUUID(),message:text.trim()}; }
