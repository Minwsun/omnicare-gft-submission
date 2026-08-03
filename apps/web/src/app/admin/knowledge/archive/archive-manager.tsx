"use client";

import { useState } from "react";
import Link from "next/link";

type ArchivedDocument = { id:string; title:string; type:string; archivedAt:string; version:string };

export default function ArchiveManager({ initialDocuments }: { initialDocuments: ArchivedDocument[] }) {
  const [documents, setDocuments] = useState(initialDocuments);
  async function restore(document: ArchivedDocument) {
    const response = await fetch(`/api/admin/kb/documents/${document.id}/restore`, { method:"POST" });
    if (!response.ok) return;
    await fetch(`/api/admin/kb/documents/${document.id}/reindex`, { method:"POST" });
    setDocuments((items)=>items.filter((item)=>item.id!==document.id));
  }
  return <><div className="knowledge-heading"><div><h1>Kho lưu trữ</h1><p>Tài liệu đã xóa khỏi Help Center và RAG.</p></div><Link href="/admin/knowledge">← Knowledge Base</Link></div><div className="data-list">{documents.map((document)=><article className="data-card" key={document.id}><header><Link href={`/admin/knowledge/${document.id}`}><b>{document.title}</b></Link><span>{document.type}</span></header><p>Đã lưu trữ {new Date(document.archivedAt).toLocaleString("vi-VN")}</p><small>Phiên bản {document.version}</small><footer><button onClick={()=>restore(document)}>Khôi phục và tái lập chỉ mục</button></footer></article>)}</div>{!documents.length&&<p className="empty-state">Kho lưu trữ đang trống.</p>}</>;
}
