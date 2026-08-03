import Link from "next/link";
import { redirect } from "next/navigation";

import { requireAdmin } from "@/lib/auth";
import LogoutButton from "@/components/logout-button";

export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const user = await requireAdmin();
  if (!user) redirect("/login");
  return <main className="admin-shell"><aside className="admin-sidebar"><Link className="brand" href="/admin">Omni<span>Care</span></Link><small>ADMIN PORTAL</small><nav><Link href="/admin">Dashboard</Link><Link href="/admin/inbox">Inbox hỗ trợ</Link><Link href="/admin/knowledge">Knowledge</Link><Link href="/admin/knowledge/archive">Archive</Link><Link href="/admin/ai-runs">AI Runs</Link></nav><span>{user.email}</span><LogoutButton /></aside><section className="admin-content">{children}</section></main>;
}
