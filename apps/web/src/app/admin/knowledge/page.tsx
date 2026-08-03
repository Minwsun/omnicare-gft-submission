import Link from "next/link";
import { prisma } from "@/lib/prisma";
import KnowledgeManager from "./knowledge-manager";

export default async function KnowledgePage({ searchParams }: { searchParams: Promise<{page?:string}> }) {
  const requestedPage=Number((await searchParams).page||"1");
  const page=Number.isInteger(requestedPage)&&requestedPage>0?requestedPage:1;
  const documents=await prisma.knowledgeDocument.findMany({where:{archivedAt:null},select:{id:true,type:true,visibility:true,authorityLevel:true,currentVersion:{select:{title:true,summary:true}},category:{select:{name:true}}},orderBy:[{authorityLevel:"desc"},{updatedAt:"desc"}],skip:(page-1)*24,take:24});
  const documentIds=documents.map((document)=>document.id);
  const [runs,total]=await Promise.all([prisma.knowledgeIngestionRun.findMany({where:{documentId:{in:documentIds}},select:{id:true,documentId:true,priority:true,status:true,stage:true,progress:true},orderBy:{createdAt:"desc"}}),prisma.knowledgeDocument.count({where:{archivedAt:null}})]);
  const latestRunByDocument=new Map<string,typeof runs[number]>();
  for(const run of runs)if(run.documentId&&!latestRunByDocument.has(run.documentId))latestRunByDocument.set(run.documentId,run);
  return <><p className="eyebrow">KNOWLEDGE MANAGEMENT</p><KnowledgeManager initialDocuments={documents.map((document)=>{const run=latestRunByDocument.get(document.id);return{id:document.id,type:document.type,visibility:document.visibility,authorityLevel:document.authorityLevel,archived:false,title:document.currentVersion?.title||"Chưa có phiên bản",summary:document.currentVersion?.summary||"",priority:run?.priority||"NORMAL",pipelineStatus:run?.status||"DONE",pipelineStage:run?.stage||null,pipelineProgress:run?.progress||0,latestRunId:run?.id||null};})}/><nav className="pagination">{page>1&&<Link href={`?page=${page-1}`}>← Trang trước</Link>}<span>Trang {page}/{Math.max(1,Math.ceil(total/24))}</span>{page*24<total&&<Link href={`?page=${page+1}`}>Trang sau →</Link>}</nav></>;
}
