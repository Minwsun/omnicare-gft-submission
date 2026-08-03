import Link from "next/link";
import { notFound } from "next/navigation";

import { prisma } from "@/lib/prisma";

function json(value: unknown) { return JSON.stringify(value, null, 2); }

export default async function AiRunDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const run = await prisma.aiRun.findUnique({ where: { id }, include: {
    conversation: { include: { customer: true, messages: { orderBy: { createdAt: "asc" } } } },
    steps: true,
    toolCalls: { orderBy: { createdAt: "asc" } },
    retrievals: { include: { version: { include: { document: true } }, chunk: true }, orderBy: { rank: "asc" } },
  } });
  if (!run) notFound();
  const latency = run.completedAt ? run.completedAt.getTime()-run.startedAt.getTime() : null;
  return <><Link className="back-link" href="/admin/ai-runs">← AI Runs</Link><p className="eyebrow">AGENT TRACE</p><h1>{run.intent ?? "UNCLASSIFIED"}</h1><p>{run.id}</p>
    <div className="fact-grid"><div><small>Trạng thái</small><b>{run.completedAt ? (run.requiresHuman ? "HANDOFF" : "COMPLETED") : "RUNNING"}</b></div><div><small>Confidence</small><b>{run.confidence?.toFixed(3) ?? "N/A"}</b></div><div><small>Tổng thời gian</small><b>{latency === null ? "Đang chạy" : `${latency} ms`}</b></div></div>
    <section className="admin-section"><h2>Ngữ cảnh</h2><article className="data-card"><p>Conversation: {run.conversationId}</p><small>{run.conversation.customer?.name ?? "Khách vãng lai"} · prompt {run.promptVersion} · {run.startedAt.toLocaleString("vi-VN")}</small></article></section>
    <section className="admin-section"><h2>Pipeline steps</h2><div className="timeline">{run.steps.map((step, index)=><article key={step.id}><header><b>{index+1}. {step.name}</b><span>{step.status} · {step.latencyMs} ms</span></header>{step.summary && <pre>{json(step.summary)}</pre>}</article>)}</div></section>
    <section className="admin-section"><h2>Tool calls</h2><div className="timeline">{run.toolCalls.map((call)=><article key={call.id}><header><b>{call.toolName}</b><span>{call.status} · {call.latencyMs} ms</span></header><small>{call.referenceId ?? "Không có reference ID"}</small><details><summary>Input đã che dữ liệu nhạy cảm</summary><pre>{json(call.inputRedacted)}</pre></details>{call.outputRedacted && <details><summary>Output đã che dữ liệu nhạy cảm</summary><pre>{json(call.outputRedacted)}</pre></details>}</article>)}</div>{!run.toolCalls.length && <p className="empty-state">Run này không gọi tool.</p>}</section>
    <section className="admin-section"><h2>Retrieval evidence</h2><div className="timeline">{run.retrievals.map((result)=><article key={result.id}><header><Link href={`/admin/knowledge/${result.version.documentId}`}><b>#{result.rank} · {result.version.title}</b></Link><span>score {result.score.toFixed(4)}</span></header><small>{result.chunk.section} · version {result.version.semanticVersion}</small><p>{result.chunk.content}</p></article>)}</div>{!run.retrievals.length && <p className="empty-state">Run này không truy xuất Knowledge Base.</p>}</section>
    <section className="admin-section"><h2>Tin nhắn hội thoại</h2><div className="timeline">{run.conversation.messages.map((message)=><article key={message.id}><header><b>{message.direction}</b><time>{message.createdAt.toLocaleString("vi-VN")}</time></header><p>{message.content}</p></article>)}</div></section>
  </>;
}
