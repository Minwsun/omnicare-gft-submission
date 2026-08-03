"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

type DocumentItem = { id:string; type:string; visibility:string; authorityLevel:number; archived:boolean; title:string; summary:string; priority:string; pipelineStatus:string; pipelineStage:string|null; pipelineProgress:number; latestRunId:string|null };
const emptyForm = { documentId:"", title:"", content:"", kind:"GUIDE", visibility:"PUBLIC", importance:"MEDIUM", mandatory:false, priority:"NORMAL" };
const stageLabels: Record<string,string> = { QUEUED:"Đang chờ worker", NORMALIZING:"Đang chuẩn hóa", CHUNKING:"Đang chia nội dung", PERSISTING:"Đang lưu tài liệu", EMBEDDING:"Đang tạo chỉ mục ngữ nghĩa", EMBEDDING_SKIPPED:"Đang dùng chỉ mục từ khóa", INDEXING:"Đang hoàn thiện chỉ mục", VALIDATING:"Đang kiểm tra", RETRY:"Đang tự thử lại", DONE:"Hoàn tất" };

export default function KnowledgeManager({ initialDocuments }: { initialDocuments: DocumentItem[] }) {
  const [documents, setDocuments] = useState(initialDocuments);
  const [form, setForm] = useState(emptyForm);
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const streams = documents.flatMap((document) => {
      if (!document.latestRunId || !["QUEUED", "RUNNING", "RETRY"].includes(document.pipelineStatus)) return [];
      const stream = new EventSource(`/api/admin/kb/ingestion-runs/${document.latestRunId}/stream`);
      stream.addEventListener("progress", (event) => {
        const run = JSON.parse((event as MessageEvent).data);
        setDocuments((items) => items.map((item) => item.id === document.id ? { ...item, pipelineStatus:run.status, pipelineStage:run.stage, pipelineProgress:run.progress || 0 } : item));
        if (["DONE", "CANCELLED", "QUARANTINED", "NOT_FOUND"].includes(run.status)) {
          stream.close();
          if (run.status === "DONE") window.location.reload();
        }
      });
      return [stream];
    });
    return () => streams.forEach((stream) => stream.close());
  }, [documents.map((document) => `${document.latestRunId}:${document.pipelineStatus}`).join("|")]);

  function label(document: DocumentItem) {
    if (document.archived) return "ĐÃ XÓA";
    if (document.pipelineStatus === "RUNNING") return `${document.pipelineStage === "EMBEDDING" ? "ĐANG TẠO EMBEDDING" : "ĐANG XỬ LÝ"} · ${document.pipelineProgress}%`;
    if (["QUEUED", "RETRY"].includes(document.pipelineStatus)) return "ĐANG CHỜ XỬ LÝ";
    if (document.pipelineStatus === "QUARANTINED") return "LỖI CHỈ MỤC";
    return "SẴN SÀNG";
  }

  function createDocument() { setForm(emptyForm); setStatus(""); setOpen(true); }
  async function editDocument(document: DocumentItem) { setStatus("Đang tải nội dung…"); const response=await fetch(`/api/admin/kb/documents/${document.id}`,{cache:"no-store"}); const detail=await response.json(); if(!response.ok){setStatus("Không thể tải tài liệu.");return;} setForm({ documentId:document.id, title:detail.title, content:detail.content, kind:document.type, visibility:document.visibility, importance:document.authorityLevel>=90?"CRITICAL":document.authorityLevel>=70?"HIGH":"MEDIUM", mandatory:["POLICY","TERMS","SOP"].includes(document.type), priority:document.priority }); setStatus(""); setOpen(true); }

  async function waitRun(runId: string) {
    for (let attempt=0; attempt<180; attempt+=1) {
      const response = await fetch(`/api/admin/kb/ingestion-runs/${runId}`, { cache:"no-store" });
      const run = await response.json();
      const stage = stageLabels[run.stage || run.status] || run.stage || run.status;
      const recovery = run.stale ? " · Worker đang tự phục hồi" : "";
      const attempt = run.attempts > 1 ? ` · lần ${run.attempts}/3` : "";
      setStatus(`${stage} · ${run.progress || 0}%${attempt}${recovery}`);
      if (run.status === "DONE") { window.location.reload(); return; }
      if (["CANCELLED","QUARANTINED"].includes(run.status)) { setBusy(false); setStatus(run.error || "Không thể xử lý tài liệu."); return; }
      await new Promise((resolve)=>setTimeout(resolve,1000));
    }
    setBusy(false); setStatus("Tác vụ vẫn chạy nền.");
  }

  async function save() {
    setBusy(true); setStatus("Đang chia tài liệu và tạo chỉ mục…");
    const response = await fetch("/api/admin/kb/auto-ingest", { method:"POST", headers:{"content-type":"application/json"}, body:JSON.stringify({ ...form, documentId:form.documentId||undefined, marketplace:"SHOPEE", autoPublish:true }) });
    const result = await response.json();
    if (!response.ok || result.status === "DUPLICATE") { setBusy(false); setStatus(result.status === "DUPLICATE" ? "Nội dung này đã tồn tại." : result.error || "Không thể lưu tài liệu."); return; }
    await waitRun(result.runId);
  }

  async function archive(document: DocumentItem) {
    if (!confirm(`Xóa “${document.title}” khỏi Knowledge Base?`)) return;
    const response = await fetch(`/api/admin/kb/documents/${document.id}/archive`, { method:"POST" });
    if (response.ok) setDocuments((items) => items.filter((item) => item.id !== document.id));
  }
  return <>
    <div className="knowledge-heading"><div><h1>Tài liệu</h1><p>Tài liệu gốc được tự động chia nhỏ và đưa vào Hybrid RAG.</p></div><div className="heading-actions"><Link href="/admin/knowledge/archive">Kho lưu trữ</Link><button onClick={createDocument}>+ Thêm tài liệu</button></div></div>
    {status && !open && <p className="knowledge-status">{status}</p>}
    <div className="knowledge-grid">{documents.map((document) => <article className="knowledge-card" key={document.id}><header><span>{document.type} · {document.priority}</span><small>{label(document)}</small></header><h2>{document.title}</h2><p>{document.summary}</p><small>{document.pipelineStage || "FULL_TEXT + VECTOR"}</small><footer><Link href={`/admin/knowledge/${document.id}`}>Chi tiết</Link><button onClick={()=>editDocument(document)}>Sửa</button><button className="danger" onClick={()=>archive(document)}>Xóa</button></footer></article>)}</div>
    {open && <div className="knowledge-modal-backdrop" onMouseDown={()=>!busy&&setOpen(false)}><section className="knowledge-modal" onMouseDown={(event)=>event.stopPropagation()}><header><div><small>{form.documentId?"CHỈNH SỬA":"TÀI LIỆU MỚI"}</small><h2>{form.title || "Tài liệu Knowledge Base"}</h2></div><button onClick={()=>setOpen(false)}>×</button></header><div className="knowledge-form"><label>Tiêu đề<input value={form.title} onChange={(event)=>setForm({...form,title:event.target.value})}/></label><div className="knowledge-form-row"><label>Loại<select value={form.kind} onChange={(event)=>setForm({...form,kind:event.target.value})}>{["FAQ","POLICY","TERMS","GUIDE","PRODUCT_GUIDE","TROUBLESHOOTING","SOP","INCIDENT","HISTORICAL_RESOLUTION"].map((value)=><option key={value}>{value}</option>)}</select></label><label>Hiển thị<select value={form.visibility} onChange={(event)=>setForm({...form,visibility:event.target.value})}>{["PUBLIC","CUSTOMER_AUTHENTICATED","INTERNAL"].map((value)=><option key={value}>{value}</option>)}</select></label><label>Độ ưu tiên<select value={form.priority} onChange={(event)=>setForm({...form,priority:event.target.value})}><option value="HIGH">Cao</option><option value="NORMAL">Bình thường</option><option value="LOW">Thấp</option></select></label></div><label>Nội dung<textarea value={form.content} onChange={(event)=>setForm({...form,content:event.target.value})}/></label>{status&&<p>{status}</p>}</div><footer><button className="secondary" onClick={()=>setOpen(false)}>Đóng</button><button disabled={busy||form.title.trim().length<1||form.content.trim().length<20} onClick={save}>{busy?"Đang tạo chỉ mục…":form.documentId?"Lưu tài liệu":"Thêm tài liệu"}</button></footer></section></div>}
  </>;
}
