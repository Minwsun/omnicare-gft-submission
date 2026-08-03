"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

type TicketSummary = { id:string; status:string; priority:string; category:string; summary:string; assignedTo:string|null; updatedAt:string; customer?:{name:string;email:string}; conversation:{title:string|null;lastMessageAt:string;_count:{messages:number}} };
type Message = { id:string; direction:"INBOUND"|"OUTBOUND"; content:string; createdAt:string; metadata?:{source?:string}; attachments?:{id:string;fileName:string}[] };
type TicketDetail = TicketSummary & { customer?:Record<string,unknown>; order?:Record<string,unknown>; events:{id:string;type:string;createdAt:string;payload?:unknown}[]; conversation:TicketSummary["conversation"] & { messages:Message[]; aiRuns:unknown[] } };
type Assist = { summary:string; missing_information:string[]; next_action:string; reply_options:string[]; warnings:string[]; contextVersion?:string };

export default function InboxClient() {
  const [tickets,setTickets]=useState<TicketSummary[]>([]);
  const [selectedId,setSelectedId]=useState<string>();
  const [detail,setDetail]=useState<TicketDetail>();
  const [adminId,setAdminId]=useState("");
  const [reply,setReply]=useState("");
  const [assist,setAssist]=useState<Assist>();
  const [assistLoading,setAssistLoading]=useState(false);
  const [busy,setBusy]=useState(false);
  const [assignment,setAssignment]=useState("all");

  const loadTickets=useCallback(async()=>{
    const response=await fetch(`/api/admin/inbox?assignment=${assignment}`,{cache:"no-store"});
    if(!response.ok)return;
    const data=await response.json();
    setTickets(data.tickets);setAdminId(data.adminId);
    setSelectedId((current)=>current??data.tickets[0]?.id);
  },[assignment]);

  const loadDetail=useCallback(async(id:string)=>{
    const response=await fetch(`/api/admin/tickets/${id}`,{cache:"no-store"});
    if(!response.ok)return undefined;
    const ticket=(await response.json()).ticket as TicketDetail;
    setDetail(ticket);
    return ticket;
  },[]);

  useEffect(()=>{const timer=setTimeout(()=>void loadTickets(),0);return()=>clearTimeout(timer);},[loadTickets]);
  useEffect(()=>{
    if(!selectedId)return;
    const timer=setTimeout(()=>void loadDetail(selectedId),0);
    return()=>clearTimeout(timer);
  },[selectedId,loadDetail]);
  useEffect(()=>{
    const timer=setInterval(()=>{void loadTickets();if(selectedId)void loadDetail(selectedId);},3000);
    return()=>clearInterval(timer);
  },[loadTickets,loadDetail,selectedId]);

  const latestInboundId=useMemo(()=>detail?.conversation.messages.findLast((message)=>message.direction==="INBOUND")?.id,[detail]);
  const assistKey=detail?`${detail.id}:${latestInboundId??"none"}:${detail.status}:${detail.assignedTo??"none"}`:undefined;

  const loadAssist=useCallback(async()=>{
    if(!selectedId)return;
    setAssistLoading(true);
    try{
      const response=await fetch(`/api/admin/tickets/${selectedId}/ai-assist`,{method:"POST"});
      if(response.ok)setAssist(await response.json());
    }finally{setAssistLoading(false);}
  },[selectedId]);

  useEffect(()=>{if(!assistKey)return;const timer=setTimeout(()=>void loadAssist(),0);return()=>clearTimeout(timer);},[assistKey,loadAssist]);

  async function action(path:string,body?:unknown){
    if(!selectedId)return;
    setBusy(true);
    try{
      const response=await fetch(`/api/admin/tickets/${selectedId}/${path}`,{method:"POST",headers:{"content-type":"application/json"},body:body?JSON.stringify(body):undefined});
      if(response.ok)await Promise.all([loadTickets(),loadDetail(selectedId)]);
    }finally{setBusy(false);}
  }

  async function send(event:FormEvent){event.preventDefault();if(!reply.trim())return;const content=reply;setReply("");await action("reply",{content});}
  const mine=detail?.assignedTo===adminId;

  return <div className="inbox-layout">
    <aside className="ticket-queue"><div className="inbox-toolbar"><select value={assignment} onChange={(event)=>setAssignment(event.target.value)}><option value="all">Tất cả</option><option value="unassigned">Chưa nhận</option><option value="mine">Của tôi</option></select><button onClick={()=>void loadTickets()}>Làm mới</button></div>{tickets.map(ticket=><button className={ticket.id===selectedId?"active":""} key={ticket.id} onClick={()=>{setSelectedId(ticket.id);setAssist(undefined);}}><span className={`priority ${ticket.priority.toLowerCase()}`}>{ticket.priority}</span><b>{ticket.customer?.name||ticket.id}</b><p>{ticket.summary}</p><small>{ticket.id} · {ticket.category} · {ticket.conversation._count.messages} tin</small></button>)}{!tickets.length&&<p className="empty-state">Không có yêu cầu đang mở.</p>}</aside>
    <section className="ticket-workspace">{detail?<><header className="ticket-header"><div><small>{detail.id} · {detail.category}</small><h2>{detail.customer?.name as string||"Khách hàng"}</h2><p>{detail.summary}</p></div><div className="ticket-actions">{!detail.assignedTo&&<button disabled={busy} onClick={()=>action("claim")}>Tham gia cuộc trò chuyện</button>}{mine&&<><button disabled={busy} onClick={()=>action("status",{action:"WAIT_CUSTOMER"})}>Chờ khách</button><button disabled={busy} onClick={()=>action("status",{action:"RESOLVE"})}>Đã xử lý</button><button disabled={busy} onClick={()=>action("status",{action:"RELEASE_AI"})}>Trả lại AI</button></>}</div></header>
      <div className="operator-grid"><div className="operator-chat"><div className="operator-messages">{detail.conversation.messages.map(message=><article key={message.id} className={message.direction==="INBOUND"?"customer":"outbound"}><small>{message.direction==="INBOUND"?"Khách hàng":message.metadata?.source==="HUMAN_ADMIN"?"Nhân viên Omni":message.metadata?.source==="SYSTEM"?"Hệ thống":"Omni AI"}</small><p>{message.content}</p><time>{new Date(message.createdAt).toLocaleString("vi-VN")}</time>{message.attachments?.map(file=><a key={file.id} href={`/api/chat/attachments/${file.id}`} target="_blank">{file.fileName}</a>)}</article>)}</div><form onSubmit={send} className="operator-composer"><textarea value={reply} onChange={event=>setReply(event.target.value)} placeholder={mine?"Nhập phản hồi cho khách hàng":"Ticket đang do nhân viên khác xử lý"} disabled={!mine||busy}/><button disabled={!mine||busy||!reply.trim()}>Gửi</button></form></div>
      <aside className="operator-assist"><div className="assist-head"><h3>Gợi ý cho nhân viên</h3><button onClick={()=>void loadAssist()} disabled={assistLoading}>{assistLoading?"Đang tạo gợi ý…":"Tạo lại"}</button></div>{assist&&<><h3>Tóm tắt</h3><p>{assist.summary}</p><h3>Bước tiếp theo</h3><p>{assist.next_action}</p>{assist.missing_information.length>0&&<><h3>Cần bổ sung</h3><ul>{assist.missing_information.map(item=><li key={item}>{item}</li>)}</ul></>}{assist.warnings.length>0&&<><h3>Cảnh báo</h3><ul>{assist.warnings.map(item=><li key={item}>{item}</li>)}</ul></>}<h3>Phản hồi gợi ý</h3>{assist.reply_options.map(option=><button className="reply-option" key={option} onClick={()=>setReply(option)}>{option}</button>)}</>} {!assist&&assistLoading&&<p>Đang đối chiếu hội thoại và dữ liệu liên quan…</p>}<details><summary>Dữ liệu liên quan</summary><pre>{JSON.stringify({customer:detail.customer,order:detail.order},null,2)}</pre></details><details><summary>Timeline</summary>{detail.events.filter(event=>event.type!=="AI_ASSIST_CACHED").map(event=><p key={event.id}><b>{event.type}</b><br/><small>{new Date(event.createdAt).toLocaleString("vi-VN")}</small></p>)}</details></aside></div>
    </>:<p className="empty-state">Chọn một yêu cầu hỗ trợ.</p>}</section>
  </div>;
}
