import { prisma } from "@/lib/prisma";

export default async function AdminPage() {
  const [documents, graphBuilds, aiRuns] = await Promise.all([
    prisma.knowledgeDocument.count({ where: { archivedAt: null } }),
    prisma.knowledgeGraphBuild.count({ where: { status: "COMPLETED" } }),
    prisma.aiRun.count(),
  ]);
  return <><p className="eyebrow">ADMIN CONTROL ROOM</p><h1>Vận hành hỗ trợ</h1><div className="metrics"><Metric value={String(documents)} label="Documents" /><Metric value={String(graphBuilds)} label="Graph builds" /><Metric value={String(aiRuns)} label="AI runs" /></div></>;
}
function Metric({ value, label }: { value: string; label: string }) { return <div className="metric"><b>{value}</b><span>{label}</span></div>; }
