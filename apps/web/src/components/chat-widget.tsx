"use client";

import Link from "next/link";
import { ChangeEvent, FormEvent, useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import AgentUiRenderer, { type UiComponent } from "@/components/agent-ui-renderer";

type Citation = { title: string; version: string; public_url?: string };
type Attachment = { id:string; fileName:string; mimeType:string; size:number; url:string };
type Message = { role: "customer" | "agent"; source?: "OMNI_AI" | "HUMAN_ADMIN" | "SYSTEM"; content: string; createdAt: string; citations?: Citation[]; handoff?: boolean; ui?: UiComponent[]; attachments?: Attachment[] };
type OrderChoice = { order_id: string; status: string; placed_at: string; total_amount: number; currency: string };
type Conversation = { id: string; title: string | null; lastMessageAt: string; _count: { messages: number } };
type Handoff = { ticketId:string; status:string; priority:string; category:string; assigned:boolean; mode:"WAITING_HUMAN"|"HUMAN_ACTIVE"|"WAITING_CUSTOMER"; updatedAt:string };

function formatChatTime(value: string) {
  const date = new Date(value);
  const options: Intl.DateTimeFormatOptions = { timeZone: "Asia/Ho_Chi_Minh", hour: "2-digit", minute: "2-digit" };
  if (date.toLocaleDateString("vi-VN", { timeZone: "Asia/Ho_Chi_Minh" }) !== new Date().toLocaleDateString("vi-VN", { timeZone: "Asia/Ho_Chi_Minh" })) Object.assign(options, { day: "2-digit", month: "2-digit", year: "numeric" });
  return new Intl.DateTimeFormat("vi-VN", options).format(date);
}

function interactionDisplayText(component: UiComponent, action: "SELECT" | "SUBMIT" | "CONFIRM" | "REJECT" | "CANCEL", values: Record<string, unknown>) {
  const optionIds = Array.isArray(values.optionIds) ? values.optionIds.map(String) : values.optionId ? [String(values.optionId)] : [];
  const labels = optionIds.map((id) => component.options?.find((option) => option.id === id)?.label).filter(Boolean);
  if (action === "SELECT") return `Tôi chọn ${labels[0] || component.title || "lựa chọn này"}.`;
  if (action === "CONFIRM") return `Tôi đồng ý ${component.title ? component.title.toLowerCase() : "thực hiện yêu cầu này"}.`;
  if (action === "REJECT") return `Tôi không đồng ý ${component.title ? component.title.toLowerCase() : "thực hiện yêu cầu này"}.`;
  if (action === "CANCEL") return `Tôi bỏ qua ${component.title ? component.title.toLowerCase() : "bước này"}.`;
  if (labels.length) return `Tôi chọn: ${labels.join(", ")}.`;
  const details = Object.entries(values)
    .filter(([key]) => key !== "optionId" && key !== "optionIds")
    .map(([key, value]) => `${component.fields?.find((field) => field.id === key)?.label || key}: ${typeof value === "object" && value && "name" in value ? String((value as { name: unknown }).name) : String(value)}`);
  return details.length ? `Tôi cung cấp ${details.join(", ")}.` : `Tôi tiếp tục ${component.title ? component.title.toLowerCase() : "yêu cầu này"}.`;
}

export default function ChatWidget() {
  const pathname = usePathname();
  const orderId = pathname.match(/^\/portal\/orders\/([^/]+)$/)?.[1];
  const pageContext = { route: pathname, ...(orderId ? { orderId: decodeURIComponent(orderId) } : {}) };
  const [open, setOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationId, setConversationId] = useState<string>();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState("");
  const [orderChoices, setOrderChoices] = useState<OrderChoice[]>([]);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [uploading, setUploading] = useState(false);
  const [handoff, setHandoff] = useState<Handoff|null>(null);

  async function loadHistory() {
    const response = await fetch("/api/chat/conversations", { cache: "no-store" });
    if (response.ok) setConversations((await response.json()).conversations);
  }

  useEffect(() => {
    fetch("/api/auth/session", { cache: "no-store" }).then(async (response) => {
      const data = await response.json().catch(() => ({}));
      const customer = response.ok && data.user?.role === "CUSTOMER";
      setAuthenticated(customer);
      if (customer) {
        await loadHistory();
      }
    });
  }, []);

  async function newConversation() {
    if (handoff && !window.confirm("Yêu cầu hỗ trợ người thật vẫn đang mở. Bạn vẫn muốn tạo cuộc trò chuyện mới?")) return;
    if (conversationId) await fetch(`/api/chat/conversations/${conversationId}/close`, { method: "POST" });
    setConversationId(undefined);
    setMessages([]);
    setOrderChoices([]);
    setAttachments([]);
    setHandoff(null);
    setHistoryOpen(false);
  }

  async function openConversation(id: string) {
    const response = await fetch(`/api/chat/conversations/${id}/messages`, { cache: "no-store" });
    if (!response.ok) return;
    const data = await response.json();
    setConversationId(id);
    setMessages(data.conversation.messages.map((message: { direction: "INBOUND" | "OUTBOUND"; content: string; createdAt: string; attachments?: Omit<Attachment,"url">[]; metadata?: { source?: "OMNI_AI" | "HUMAN_ADMIN" | "SYSTEM"; citations?: Citation[]; requires_human?: boolean; ui?: UiComponent[] } }) => ({ role: message.direction === "INBOUND" ? "customer" : "agent", source: message.metadata?.source ?? (message.direction === "OUTBOUND" ? "OMNI_AI" : undefined), content: message.content, createdAt: message.createdAt, citations: message.metadata?.citations, handoff: message.metadata?.requires_human, ui: message.metadata?.ui, attachments:message.attachments?.map((item)=>({...item,url:`/api/chat/attachments/${item.id}`})) })));
    const handoffResponse = await fetch(`/api/chat/handoff?conversationId=${id}`, { cache: "no-store" });
    if (handoffResponse.ok) setHandoff((await handoffResponse.json()).handoff);
    setHistoryOpen(false);
  }

  async function cancelHandoff() {
    if (!conversationId) return;
    const response = await fetch(`/api/chat/handoff?conversationId=${conversationId}`, { method: "DELETE" });
    if (response.ok) setHandoff(null);
  }

  useEffect(() => {
    if (!open || !conversationId || !handoff) return;
    const timer = setInterval(() => { void openConversation(conversationId); }, 4000);
    return () => clearInterval(timer);
  }, [open, conversationId, handoff?.ticketId]);

  async function selectImages(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files || []).slice(0, Math.max(0, 5 - attachments.length));
    event.target.value = "";
    if (!files.length) return;
    setUploading(true); setProgress("Đang tải ảnh kiện hàng…");
    try {
      let activeConversationId = conversationId;
      if (!activeConversationId) {
        const created = await fetch("/api/chat/conversations", { method:"POST" });
        if (!created.ok) throw new Error("CONVERSATION_CREATE_FAILED");
        activeConversationId = (await created.json()).conversation.id;
        setConversationId(activeConversationId);
      }
      const uploaded: Attachment[] = [];
      for (const file of files) {
        const form = new FormData(); form.set("conversationId", activeConversationId!); form.set("file", file);
        const response = await fetch("/api/chat/attachments", { method:"POST", body:form });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "IMAGE_UPLOAD_FAILED");
        uploaded.push(data.attachment);
      }
      setAttachments((items)=>[...items,...uploaded].slice(0,5));
      setProgress("Đã tải ảnh. Bạn có thể gửi ngay.");
    } catch (error) {
      setProgress(`Không thể tải ảnh: ${error instanceof Error ? error.message : "UNKNOWN_ERROR"}`);
    } finally { setUploading(false); }
  }

  async function submitInteraction(component: UiComponent, action: "SELECT" | "SUBMIT" | "CONFIRM" | "REJECT" | "CANCEL", values: Record<string, unknown> = {}) {
    if (!conversationId || !component.continuation_token) {
      setMessages((items) => [...items, { role: "agent", content: "Lựa chọn này đã hết hạn hoặc chưa sẵn sàng. Bạn gửi lại yêu cầu để mình tải danh sách mới nhé.", createdAt: new Date().toISOString() }]);
      return;
    }
    setLoading(true);
    setProgress(action === "SELECT" ? "Đang kiểm tra lựa chọn của bạn…" : "Đang thực hiện yêu cầu…");
    const displayText = interactionDisplayText(component, action, values).slice(0, 1000);
    setMessages((items) => [...items.map((item) => ({ ...item, ui: item.ui?.filter((ui) => ui.id !== component.id) })), { role: "customer", content: displayText, createdAt: new Date().toISOString() }]);
    try {
      const response = await fetch("/api/chat/interactions", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ interactionId: component.id, conversationId, action, values, displayText, continuationToken: component.continuation_token }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.answer || data.error || "CONFIRMATION_FAILED");
      setMessages((items) => [...items, { role: "agent", content: data.answer, createdAt: new Date().toISOString(), citations: data.citations, handoff: data.requires_human, ui: data.ui }]);
    } catch (error) {
      setMessages((items) => [...items, { role: "agent", content: `Chưa thể thực hiện yêu cầu: ${error instanceof Error ? error.message : "UNKNOWN_ERROR"}.`, createdAt: new Date().toISOString(), handoff: true }]);
    } finally {
      setProgress("");
      setLoading(false);
    }
  }

  async function send(event: FormEvent) {
    event.preventDefault();
    const content = input.trim();
    if ((!content && attachments.length===0) || loading || uploading || !authenticated) return;
    const sentAttachments = attachments;
    const displayContent = content || "Tôi gửi ảnh kiện hàng.";
    setMessages((items) => [...items, { role: "customer", content:displayContent, createdAt: new Date().toISOString(), attachments:sentAttachments }]);
    setInput("");
    setAttachments([]);
    setLoading(true);
    setProgress("Đang tìm hiểu yêu cầu của bạn…");
    try {
      const response = await fetch("/api/chat/stream", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ content:displayContent, conversationId, pageContext, attachmentIds:sentAttachments.map((item)=>item.id) }) });
      if (!response.ok || !response.body) throw new Error("AGENT_STREAM_UNAVAILABLE");
      const activeConversationId = response.headers.get("x-conversation-id") ?? conversationId;
      setConversationId(activeConversationId);
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      const handleBlock = (block: string) => {
        const type = block.match(/^event: (.+)$/m)?.[1];
        const raw = block.match(/^data: (.+)$/m)?.[1];
        if (!type || !raw) return;
        const data = JSON.parse(raw);
        if (type === "progress") setProgress(data.label);
        if (type === "response_started") setProgress("");
        if (type === "token") {
          setProgress("");
          setMessages((items) => items.at(-1)?.role === "agent"
            ? items.map((item, index) => index === items.length - 1 ? { ...item, content: item.content + data.token } : item)
            : [...items, { role: "agent", content: data.token, createdAt: new Date().toISOString() }]);
        }
        if (type === "order_choices") setOrderChoices(data.orders);
        if (type === "done") {
          setProgress("");
          const answer = { role: "agent" as const, content: data.answer, createdAt: new Date().toISOString(), citations: data.citations, handoff: data.requires_human, ui: data.ui };
          setMessages((items) => items.at(-1)?.role === "agent" ? items.map((item, index) => index === items.length - 1 ? answer : item) : [...items, answer]);
        }
        if (type === "error") throw new Error(data.code);
      };
      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          buffer += decoder.decode();
          if (buffer.trim()) handleBlock(buffer);
          break;
        }
        buffer += decoder.decode(value, { stream: true }).replaceAll("\r\n", "\n");
        const blocks = buffer.split("\n\n");
        buffer = blocks.pop() ?? "";
        blocks.forEach(handleBlock);
      }
      await loadHistory();
      if (activeConversationId) {
        const handoffResponse = await fetch(`/api/chat/handoff?conversationId=${activeConversationId}`, { cache: "no-store" });
        if (handoffResponse.ok) setHandoff((await handoffResponse.json()).handoff);
      }
    } catch (error) {
      setProgress("");
      const code = error instanceof Error ? error.message : "AGENT_RUN_FAILED";
      setMessages((items) => [...items, { role: "agent", content: `Không thể kết nối AI: ${code}.`, createdAt: new Date().toISOString(), handoff: true }]);
    } finally {
      setLoading(false);
    }
  }

  if (pathname.startsWith("/admin")) return null;

  return <div className="chat-widget">
    {open && <section className="chat-popup">
      <header className="widget-head"><div><b>OmniCare AI</b><small>{orderId ? `Đang hỗ trợ đơn ${orderId}` : authenticated ? "Hỗ trợ tài khoản và đơn hàng" : "Đăng nhập để tra cứu giao dịch"}</small></div><div><button onClick={() => setHistoryOpen((value) => !value)} title="Lịch sử">☰</button><button onClick={() => setOpen(false)} title="Thu gọn">×</button></div></header>
      {historyOpen ? <div className="conversation-history"><button className="new-chat" onClick={newConversation}>＋ Trò chuyện mới</button>{conversations.map((conversation) => <button key={conversation.id} onClick={() => openConversation(conversation.id)}><b>{conversation.title || "Cuộc trò chuyện mới"}</b><small>{conversation._count.messages} tin nhắn · {formatChatTime(conversation.lastMessageAt)}</small></button>)}</div> : <>
        <div className="widget-messages">
          {messages.length === 0 && <p className="widget-empty">{orderId ? `Hỏi về giao hàng, thanh toán, hủy hoặc trả đơn ${orderId}.` : "Hỏi về đơn hàng, thanh toán, giao hàng hoặc chính sách."}</p>}
          {orderId && messages.length === 0 && <div className="chat-quick-actions"><button onClick={() => setInput("Đơn này đang ở đâu?")}>Theo dõi đơn</button><button onClick={() => setInput("Đơn này có thể hủy không?")}>Kiểm tra hủy đơn</button><button onClick={() => setInput("Đơn này có thể trả hàng không?")}>Kiểm tra trả hàng</button></div>}
          {messages.map((message, index) => message.content && <div key={index} className={`message ${message.role} ${message.source?.toLowerCase() ?? ""}`}><small>{message.role === "customer" ? "Bạn" : message.source === "HUMAN_ADMIN" ? "Nhân viên Omni" : message.source === "SYSTEM" ? "Hệ thống" : "Omni AI"} · <time dateTime={message.createdAt} title={new Date(message.createdAt).toLocaleString("vi-VN", { timeZone: "Asia/Ho_Chi_Minh" })}>{formatChatTime(message.createdAt)}</time></small><p>{message.content}</p>{message.attachments?.length?<div className="chat-attachments">{message.attachments.map((item)=><a href={item.url} target="_blank" rel="noreferrer" key={item.id}><img src={item.url} alt={item.fileName}/></a>)}</div>:null}{message.citations?.map((citation) => citation.public_url && <Link className="citation" href={citation.public_url} key={`${citation.title}-${citation.version}`}>Nguồn: {citation.title}</Link>)}{message.ui?.map((component) => <AgentUiRenderer key={component.id} component={component} disabled={loading} onSubmit={submitInteraction} />)}{message.handoff && <span className="handoff">Cần nhân viên hỗ trợ</span>}</div>)}
          {handoff && <div className={`handoff-card ${handoff.mode.toLowerCase()}`}><b>{handoff.mode === "HUMAN_ACTIVE" ? "Nhân viên đã tham gia" : handoff.mode === "WAITING_CUSTOMER" ? "Đang chờ bạn bổ sung" : "Đang chờ nhân viên"}</b><small>{handoff.ticketId} · {handoff.priority}</small>{handoff.mode === "WAITING_HUMAN" && <button onClick={cancelHandoff}>Hủy yêu cầu</button>}</div>}
          {progress && <div className="agent-progress" role="status" aria-live="polite" aria-atomic="true"><span aria-hidden="true" /><p>{progress}</p></div>}
          {orderChoices.length > 0 && <div className="order-choices">{orderChoices.map((order) => <button key={order.order_id} onClick={() => setInput(`Kiểm tra đơn ${order.order_id}`)}><b>{order.order_id}</b><span>{order.status}</span><small>{order.total_amount.toLocaleString("vi-VN")} {order.currency}</small></button>)}</div>}
        </div>
        {authenticated ? <><div className="attachment-drafts">{attachments.map((item)=><div key={item.id}><img src={item.url} alt={item.fileName}/><button type="button" onClick={()=>setAttachments((items)=>items.filter((candidate)=>candidate.id!==item.id))}>×</button></div>)}</div><form className="widget-form" onSubmit={send}><label className="attachment-button" title="Gửi ảnh kiện hàng">📎<input type="file" accept="image/jpeg,image/png,image/webp" multiple onChange={selectImages} disabled={loading||uploading||attachments.length>=5}/></label><input value={input} onChange={(event) => setInput(event.target.value)} placeholder={orderId ? `Hỏi về ${orderId}` : "Nhập câu hỏi hoặc mã đơn"} /><button disabled={loading||uploading}>{uploading?"↑":loading ? "…" : "Gửi"}</button></form></> : <div className="widget-login"><Link href="/login">Đăng nhập để bắt đầu</Link></div>}
      </>}
    </section>}
    <button className="chat-launcher" onClick={() => setOpen((value) => !value)} aria-label="Mở hỗ trợ">{open ? "×" : "Chat"}</button>
  </div>;
}
