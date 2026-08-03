"use client";

import Link from "next/link";
import { FormEvent, useRef, useState } from "react";

type Citation = { title: string; version: string; section: string; public_url?: string };
type Message = { role: "customer" | "agent"; content: string; createdAt: string; citations?: Citation[]; handoff?: boolean };

export default function ChatClient() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const conversationId = useRef<string | undefined>(undefined);

  async function send(event: FormEvent) {
    event.preventDefault();
    const content = input.trim();
    if (!content || loading) return;
    const createdAt = new Date().toISOString();
    setMessages((items) => [...items, { role: "customer", content, createdAt }, { role: "agent", content: "", createdAt }]);
    setInput("");
    setLoading(true);
    try {
      const response = await fetch("/api/chat/stream", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ content, conversationId: conversationId.current }) });
      if (!response.ok || !response.body) throw new Error("AGENT_STREAM_UNAVAILABLE");
      conversationId.current = response.headers.get("x-conversation-id") ?? conversationId.current;
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const blocks = buffer.split("\n\n");
        buffer = blocks.pop() ?? "";
        for (const block of blocks) {
          const type = block.match(/^event: (.+)$/m)?.[1];
          const raw = block.match(/^data: (.+)$/m)?.[1];
          if (!type || !raw) continue;
          const data = JSON.parse(raw);
          if (type === "token") setMessages((items) => items.map((item, index) => index === items.length - 1 ? { ...item, content: item.content + data.token } : item));
          if (type === "done") setMessages((items) => items.map((item, index) => index === items.length - 1 ? { role: "agent", content: data.answer, createdAt: item.createdAt, citations: data.citations, handoff: data.requires_human } : item));
          if (type === "error") throw new Error(data.code);
        }
      }
    } catch (error) {
      const code = error instanceof Error ? error.message : "AGENT_RUN_FAILED";
      setMessages((items) => items.map((item, index) => index === items.length - 1 ? { role: "agent", content: `Không thể kết nối AI: ${code}. Yêu cầu cần nhân viên tiếp nhận.`, createdAt: item.createdAt, handoff: true } : item));
    } finally {
      setLoading(false);
    }
  }

  return <section className="chat-card"><div className="messages">{messages.map((message, index) => <div key={index} className={`message ${message.role}`}><small>{message.role === "customer" ? "Bạn" : "Omni AI"} · <time dateTime={message.createdAt}>{new Date(message.createdAt).toLocaleString("vi-VN", { timeZone: "Asia/Ho_Chi_Minh" })}</time></small><p>{message.content}</p>{message.citations?.map((citation) => citation.public_url && <Link className="citation" key={`${citation.title}-${citation.version}`} href={citation.public_url}>Nguồn: {citation.title} · {citation.version}</Link>)}{message.handoff && <span className="handoff">Cần nhân viên hỗ trợ</span>}</div>)}{loading && <div className="message agent">Đang tra cứu dữ liệu và nguồn liên quan…</div>}</div><form onSubmit={send}><input value={input} onChange={(event) => setInput(event.target.value)} placeholder="Nhập câu hỏi hoặc mã đơn hàng" /><button disabled={loading}>Gửi</button></form></section>;
}
