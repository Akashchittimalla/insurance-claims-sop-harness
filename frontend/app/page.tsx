"use client";

import { useEffect, useRef, useState } from "react";
import {
  Activity, ArrowUp, Check, ChevronDown, CircleHelp, ClipboardCheck, FileText, FlaskConical,
  Headphones, LockKeyhole, MessageCircle, Plus, ShieldCheck, Sparkles, Terminal, UserRound, X,
} from "lucide-react";
import {
  displayMessage, isDiagnostics, isReply, isWorkspace, makeMessage, phases, request, RequestError,
  userError, validMessage, type Diagnostics, type Phase, type Workspace,
} from "../lib/client";
import { examples, opening } from "../lib/scenarios";

const steps = ["Verify identity", "Understand request", "Process claim", "Follow-up"];
const icons = [ShieldCheck, MessageCircle, FileText, ClipboardCheck];
const phaseNotes = ["Protect your information", "Identify the right claim", "Review the details", "Close the conversation"];
type Message = { id:string; role:"assistant"|"customer"; text:string; time:number };
const greeting:Message = {id:"hello",role:"assistant",text:"Hi, I’m ClaimAssist. I can help you understand a claim, check its status, or find out what to do next.",time:0};
const sessionCreated = (value:unknown): value is {session_id:string} =>
  !!value && typeof value==="object" && "session_id" in value && typeof value.session_id==="string";
const unlocked = (value:unknown): value is {unlocked:true} =>
  !!value && typeof value==="object" && "unlocked" in value && value.unlocked===true;
type ConsentDemo = {request_id:string;status:string;poll_count:number};
const isConsentDemo = (value:unknown): value is ConsentDemo =>
  !!value && typeof value==="object" && "request_id" in value && typeof value.request_id==="string" &&
  "status" in value && typeof value.status==="string" && "poll_count" in value && typeof value.poll_count==="number";
const label = (value:string) => value.replaceAll("_"," ");
const clock = (time:number) => time ? new Date(time).toLocaleTimeString([], {hour:"numeric",minute:"2-digit"}) : "";

function Workflow({phase,status}:{phase:Phase;status:string}) {
  const current=phases.indexOf(phase);
  return <ol className="workflow" aria-label="Workflow progress">{steps.map((step,index)=>{
    const Icon=icons[index];
    const done=index<current || status==="completed";
    const active=index===current&&!done;
    return <li key={step} aria-current={active?"step":undefined} className={done?"done":active?"active":""}>
      <span className="step-icon">{done?<Check size={19}/>:<Icon size={19}/>}</span>
      <div><strong>{step}</strong><small>{active&&status==="handoff"?"Human assistance":phaseNotes[index]}</small></div>
    </li>;
  })}</ol>;
}

function Developer({details,fetching,unlock}:{details:Diagnostics|null;fetching:boolean;unlock:(key:string)=>void}) {
  const [key,setKey]=useState("");
  if(!details) return <section className="side-card"><div className="card-title"><Terminal size={18}/><h2>Developer access</h2></div>
    <p>Diagnostics require an authorized demo key.</p>
    <form onSubmit={e=>{e.preventDefault();unlock(key);setKey("");}}>
      <label htmlFor="demoKey">Demo key</label><input id="demoKey" type="password" value={key} onChange={e=>setKey(e.target.value)} autoComplete="off"/>
      <button className="secondary" disabled={fetching||!key}>Unlock diagnostics</button>
    </form></section>;
  const recovery=details.events.findLast(e=>e.event_type==="recovery_strategy_selected");
  return <>
    <section className="side-card"><div className="card-title"><Terminal size={18}/><h2>Execution state</h2></div>
      <dl className="facts"><div><dt>Matched fields</dt><dd>{details.matched} / {details.required}</dd></div>
        <div><dt>Emotion signal</dt><dd>{label(details.emotion||"none")}</dd></div>
        <div><dt>Scope violations</dt><dd>{details.scope_count}</dd></div>
        <div><dt>Verification refusals</dt><dd>{details.refusals}</dd></div>
        {recovery?.action&&<div><dt>Recovery</dt><dd>{label(recovery.action)}</dd></div>}</dl>
    </section>
    <section className="side-card"><div className="card-title"><Activity size={18}/><h2>Remembered hints</h2></div>
      <p>Unverified conversation context</p><dl className="facts">
        <div><dt>Intent</dt><dd>{details.intent ? label(details.intent).toLowerCase() : "—"}</dd></div>
        {details.secondary_intents.length>0&&<div><dt>Other intents</dt><dd>{details.secondary_intents.map(label).join(", ")}</dd></div>}
        {Object.entries(details.hints).filter(([,value])=>value!==null).map(([field,value])=><div key={field}>
          <dt>{label(field)}</dt><dd>{value}{details.origin_phases["claim_hints."+field]&&
            <small> · {label(details.origin_phases["claim_hints."+field]).toLowerCase()}</small>}</dd></div>)}
        {!!details.pending.length&&<div><dt>Pending</dt><dd>{details.pending.map(label).join(", ")}</dd></div>}
      </dl>
    </section>
    <section className="side-card"><div className="card-title"><Activity size={18}/><h2>Execution timeline</h2></div>
      <ol className="timeline">{details.events.slice().reverse().map(e=><li key={e.event_id} className={e.decision==="denied"?"denied":""}>
        <strong>{label(e.event_type)}</strong><span>{label(e.phase)} · {clock(Date.parse(e.timestamp))}</span>
        {[e.action,e.decision,e.reason].filter(Boolean).map((v,i)=><small key={i}>{label(v!)}</small>)}
      </li>)}</ol>
    </section>
  </>;
}

export default function Home() {
  const [state,setState]=useState<Workspace|null>(null);
  const [messages,setMessages]=useState<Message[]>([]);
  const [text,setText]=useState("");
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [developer,setDeveloper]=useState(false);
  const [details,setDetails]=useState<Diagnostics|null>(null);
  const [unlocking,setUnlocking]=useState(false);
  const [consentDemo,setConsentDemo]=useState<ConsentDemo|null>(null);
  const pending=useRef<ReturnType<typeof makeMessage>|null>(null);
  const actionLock=useRef(false);
  const composer=useRef<HTMLTextAreaElement>(null);
  const chatEnd=useRef<HTMLDivElement>(null);

  async function refresh(withDetails=false, signal?:AbortSignal) {
    const next=await request("workspace",isWorkspace,undefined,signal);
    setState(next);
    if(withDetails) setDetails(await request("events",isDiagnostics,undefined,signal).catch(()=>null));
    return next;
  }

  useEffect(()=>{
    const controller=new AbortController();
    async function initialize(){
      try {
        const saved=await refresh(false,controller.signal);
        setMessages(saved.transcript.map(item=>({id:item.message_id+"-reply",
          role:"assistant",text:item.response,time:0})));
      }
      catch(e){
        if(controller.signal.aborted)return;
        if(e instanceof RequestError&&e.status===404) {
          await request("session",sessionCreated,{},controller.signal);
          await refresh(false,controller.signal);
        } else throw e;
      }
    }
    initialize().catch(e=>{if(!controller.signal.aborted)setError(userError(e));});
    return ()=>controller.abort();
  },[]);
  useEffect(()=>{if(messages.length) chatEnd.current?.scrollIntoView({block:"nearest"});},[messages,busy]);

  async function newSession(){
    if(actionLock.current)return;
    actionLock.current=true;setBusy(true);setError("");
    try {
      await request("session",sessionCreated,{});
      setMessages([]);setDetails(null);setDeveloper(false);setConsentDemo(null);setText("");pending.current=null;
      await refresh();
    }catch(e){setError(userError(e));}
    finally{setBusy(false);actionLock.current=false;}
  }

  async function send(value=text, retry=false){
    if(actionLock.current||!state||state.status==="completed"||!validMessage(value))return;
    const submitted=retry&&pending.current ? pending.current : makeMessage(value);
    pending.current=submitted;
    actionLock.current=true;setBusy(true);setError("");setText("");
    if(!retry)setMessages(prev=>[...prev,{id:submitted.message_id,role:"customer",
      text:displayMessage(submitted.message,state.phase),time:Date.now()}]);
    try {
      const result=await request("messages",isReply,submitted);
      pending.current=null;
      setMessages(prev=>[...prev,{id:result.message_id+"-reply",role:"assistant",text:result.response,time:Date.now()}]);
      setState(prev=>prev&&({...prev,phase:result.phase,status:result.session_status}));
      await refresh(developer);
    }catch(e){setError(userError(e));}
    finally{setBusy(false);actionLock.current=false;}
  }

  async function choose(choice:"send"|"skip"){
    if(actionLock.current||!state?.summary||!state.summary.actions.includes(choice))return;
    actionLock.current=true;setBusy(true);setError("");
    try {
      await request("summary",sessionCreated,{choice,revision:state.summary.revision});
      await refresh(developer);
    }catch(e){setError(userError(e)); await refresh(developer).catch(()=>null);}
    finally{setBusy(false);actionLock.current=false;}
  }

  async function unlock(key:string){
    setUnlocking(true);setError("");
    try {await request("unlock",unlocked,{key});setDetails(await request("events",isDiagnostics));}
    catch{setError("Developer diagnostics are unavailable. Check the demo key and server configuration.");}
    finally{setUnlocking(false);}
  }

  function fill(suggestion:string){setText(suggestion);composer.current?.focus();}
  function changeView(){
    setDeveloper(value=>!value);
    if(!developer&&state) request("events",isDiagnostics).then(setDetails).catch(()=>setDetails(null));
  }

  async function simulateConsent(poll=false){
    if(!details||state?.verification!=="verified"){
      setError("Verify the demo customer and unlock developer diagnostics to run the consent timeout scenario.");
      return;
    }
    if(actionLock.current)return;
    actionLock.current=true;setBusy(true);setError("");
    try {
      const result=await request("consent-demo",isConsentDemo,poll&&consentDemo?
        {command:"poll",request_id:consentDemo.request_id}:{command:"start"});
      setConsentDemo(result);await refresh(developer);
    }catch(e){setError(userError(e));}
    finally{setBusy(false);actionLock.current=false;}
  }

  const claim=state?.claim||state?.summary?.claim;
  const complete=state?.status==="completed";
  const stage=complete?"Conversation complete":state?.status==="handoff"?"Human assistance":state?"Session active":"Connecting";
  return <>
    <header className="top"><div className="top-inner">
      <a href="/" className="brand" aria-label="ClaimAssist AI home"><span className="brand-icon"><ShieldCheck size={23}/></span>
        <span>ClaimAssist <b>AI</b><small>Insurance Claims Support</small></span></a>
      <div className="header-actions">
        {state&&<span className="mode-tag"><FlaskConical size={13}/>{state.provider==="mock"?"Mock provider":"Live provider"}</span>}
        <button className="view-button" onClick={changeView} aria-pressed={developer}><Terminal size={16}/><span>{developer?"Customer view":"Developer view"}</span></button>
        <button className="new-button" onClick={newSession} disabled={busy}><Plus size={17}/> <span>New conversation</span></button>
      </div>
    </div></header>
    <main className="shell">
      <div className="intro"><div><p className="eyebrow">SUPPORT WORKSPACE</p><h1>Claims support</h1>
        <p>Get clear answers and next steps for your insurance claim.</p></div>
        <span className={"session-pill "+(state?"online":"")} role="status"><i/>{error&&!state?"Connection unavailable":stage}</span>
      </div>
      {state&&<Workflow phase={state.phase} status={state.status}/>}
      <div className="workspace">
        <section className="chat" aria-label="Claims conversation">
          <div className="chat-title"><span className="square"><MessageCircle size={19}/></span><div><h2>Conversation</h2><small>ClaimAssist support agent</small></div>
            <span className="secure"><LockKeyhole size={13}/> Secure session</span>
          </div>
          <div className="chat-feed" role="log" aria-live="polite" aria-relevant="additions">
            {messages.length===0&&<div className="welcome">
              <span className="welcome-icon"><ShieldCheck size={30}/></span>
              <h3>How can we help with your claim?</h3><p>{greeting.text}</p>
              <div className="starter-list">
                <button onClick={()=>fill("Can you check the status of my claim?")}><Activity/> Check claim status</button>
                <button onClick={()=>fill("Why was my claim denied?")}><CircleHelp/> Understand a denial</button>
                <button onClick={()=>fill("What documents do I need?")}><FileText/> Review documents</button>
              </div>
            </div>}
            {messages.map(item=><div className={"message "+item.role} key={item.id}>
              <span className="avatar">{item.role==="assistant"?<ShieldCheck size={17}/>:<UserRound size={17}/>}</span>
              <div><div className="message-meta">{item.role==="assistant"?"ClaimAssist":"You"} <time>{clock(item.time)}</time></div>
                <p>{item.text}</p></div>
            </div>)}
            {busy&&<div className="working" role="status"><Sparkles size={16}/>Processing your request…</div>}
            <div ref={chatEnd}/>
          </div>
          {error&&<div className="error" role="alert"><span>{error}</span>
            {pending.current&&<button onClick={()=>send(pending.current!.message,true)} disabled={busy}>Retry</button>}
            <button aria-label="Dismiss error" onClick={()=>setError("")}><X size={15}/></button></div>}
          {(state?.human_offer||state?.status==="handoff")&&<div className="context-actions">
            {state.human_offer&&<button className="secondary" onClick={()=>send("I want to speak with a person.")} disabled={busy}>Request human assistance</button>}
            {state.status==="handoff"&&<><button className="secondary" onClick={()=>send("Handoff status")} disabled={busy}>Check handoff</button>
              {state.verification!=="locked"&&<button className="secondary" onClick={()=>send("Resume")} disabled={busy}>Resume conversation</button>}</>}
          </div>}
          {complete?<div className="completed" role="status"><Check size={19}/><div><strong>Your support conversation is complete.</strong><p>{state.summary?.disposition==="simulated"?"Email delivery was simulated. No real email was sent.":"No summary email was requested."}</p></div></div>:
          <form className="compose" onSubmit={e=>{e.preventDefault();void send();}}>
            <label htmlFor="message" className="sr-only">Your message</label>
            <div className="input-wrap"><textarea id="message" ref={composer} value={text} maxLength={4000}
              placeholder="Type your message…" rows={2} onChange={e=>setText(e.target.value)}
              onKeyDown={e=>{if(e.key==="Enter"&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();void send();}}}/>
              <button className="send" type="submit" aria-label="Send message" disabled={busy||!state||!validMessage(text)}><ArrowUp size={20}/></button></div>
            <small><LockKeyhole size={12}/> Use synthetic information only.</small>
          </form>}
        </section>

        <aside className="sidebar" aria-label="Session information">
          <section className="side-card overview">
            <div className="card-title"><Activity size={19}/><h2>Session overview</h2></div>
            <div className="overview-row"><span className={"tile-icon "+(state?.verification==="verified"?"success":"")}><ShieldCheck size={18}/></span>
              <div><strong>Identity verification</strong><small>{state?.verification==="verified"?"Verified by the backend":
                state?.verification==="locked"?"Locked · human review required":"Required for protected claim details"}</small></div></div>
            <div className="overview-row"><span className="tile-icon"><FileText size={18}/></span>
              <div><strong>{claim?.case_id||"Claim context"}</strong><small>{claim?claim.type+" · "+claim.status+" · "+claim.created_at:
                "Available after claim resolution"}</small></div></div>
            {state?.handoff&&<div className="overview-row"><span className="tile-icon"><Headphones size={18}/></span>
              <div><strong>Simulated handoff</strong><small>{label(state.handoff)}</small></div></div>}
          </section>
          {state?.summary&&<section className="side-card"><div className="card-title"><ClipboardCheck size={19}/><h2>Discussion summary</h2></div>
            {state.summary.claim&&<p>Recorded claim status: <strong>{state.summary.claim.status}</strong></p>}
            <ul className="topics">{state.summary.topics.map(topic=><li key={topic}>{topic}</li>)}</ul>
            {!!state.summary.documents.length&&<p>Documents: {state.summary.documents.join(", ")}</p>}
            {state.summary.recipient&&state.summary.actions.includes("send")&&<p>Demo recipient: {state.summary.recipient}</p>}
            {state.summary.actions.length>0&&<div className="summary-actions">
              {state.summary.actions.includes("send")&&<button className="primary" disabled={busy} onClick={()=>choose("send")}>Send email summary</button>}
              {state.summary.actions.includes("skip")&&<button className="secondary" disabled={busy} onClick={()=>choose("skip")}>Skip email</button>}</div>}
            {state.summary.disposition==="simulated"&&<p role="status">Email delivery simulated.</p>}
            {state.summary.disposition==="declined"&&<p role="status">Email skipped.</p>}
          </section>}
          {(!state||state.demo)&&<section className="side-card demo-card">
            <div className="card-title"><FlaskConical size={19}/><h2>Demo scenarios</h2></div>
            <p>Try a synthetic conversation with the agent.</p>
            <button className="demo-button" onClick={()=>fill(opening)} disabled={complete}>Load Margaret’s claim scenario</button>
            <div className="select-wrap"><label className="sr-only" htmlFor="scenario">More scenarios</label>
              <select id="scenario" disabled={complete||busy} value="" onChange={e=>{
                if(e.target.value==="timeout") {void simulateConsent();return;}
                const pick=examples[Number(e.target.value)];if(pick)fill(pick[1]);
              }}>
                <option value="" disabled>More scenarios</option>{examples.map(([title],i)=><option value={i} key={title}>{title}</option>)}
                <option value="timeout">Consent timeout (developer)</option></select><ChevronDown size={16}/>
            </div>
            {developer&&consentDemo&&<div className="context-actions"><p role="status">Consent simulation: {label(consentDemo.status)} · {consentDemo.poll_count} polls</p>
              {consentDemo.status==="pending"&&<button className="secondary" onClick={()=>simulateConsent(true)} disabled={busy}>Poll demo consent</button>}
            </div>}
          </section>}
          {developer&&<Developer details={details} fetching={unlocking} unlock={unlock}/>}
        </aside>
      </div>
      <footer><ShieldCheck size={14}/> ClaimAssist AI <span>·</span> Insurance support demo</footer>
    </main>
  </>;
}
