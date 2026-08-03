import Link from "next/link";
import { Prisma } from "@prisma/client";

import { prisma } from "@/lib/prisma";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export default async function AiRunsPage({ searchParams }: { searchParams: SearchParams }) {
  const query = await searchParams;
  const requestedPage = Number(typeof query.page === "string" ? query.page : "1");
  const page = Number.isInteger(requestedPage) && requestedPage > 0 ? requestedPage : 1;
  const search = typeof query.search === "string" ? query.search.trim() : "";
  const handoff = query.handoff === "true";
  const where: Prisma.AiRunWhereInput = { ...(handoff ? { requiresHuman: true } : {}), ...(search ? { OR: [{ id: { contains: search, mode: "insensitive" } }, { conversationId: { contains: search, mode: "insensitive" } }, { intent: { contains: search, mode: "insensitive" } }] } : {}) };
  const [runs,total] = await Promise.all([prisma.aiRun.findMany({ where, select:{id:true,intent:true,requiresHuman:true,startedAt:true,completedAt:true,_count:{select:{steps:true,toolCalls:true,retrievals:true}}}, orderBy: { startedAt: "desc" }, skip:(page-1)*25, take:25 }),prisma.aiRun.count({where})]);
  return <><p className="eyebrow">AGENT OBSERVABILITY</p><h1>AI Runs</h1><form className="admin-filters"><input name="search" defaultValue={search} placeholder="Run, conversation, intent…"/><label className="checkbox-filter"><input type="checkbox" name="handoff" value="true" defaultChecked={handoff}/> Chỉ handoff</label><button>Tìm</button></form><div className="data-list">{runs.map((run) => { const latency = run.completedAt ? run.completedAt.getTime()-run.startedAt.getTime() : null; return <Link className="data-card" href={`/admin/ai-runs/${run.id}`} key={run.id}><header><b>{run.intent ?? "UNCLASSIFIED"}</b><span>{run.completedAt ? (run.requiresHuman ? "HANDOFF" : "COMPLETED") : "RUNNING"}</span></header><p>{run.id}</p><small>{run._count.steps} steps · {run._count.toolCalls} tools · {run._count.retrievals} evidence · {latency === null ? "đang chạy" : `${latency} ms`}</small></Link>})}</div>{!runs.length && <p className="empty-state">Không tìm thấy AI run phù hợp.</p>}<nav className="pagination">{page>1&&<Link href={`?page=${page-1}&search=${encodeURIComponent(search)}${handoff?"&handoff=true":""}`}>← Trang trước</Link>}<span>Trang {page}/{Math.max(1,Math.ceil(total/25))}</span>{page*25<total&&<Link href={`?page=${page+1}&search=${encodeURIComponent(search)}${handoff?"&handoff=true":""}`}>Trang sau →</Link>}</nav></>;
}
