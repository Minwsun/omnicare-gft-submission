import Link from "next/link";
import { redirect } from "next/navigation";

import { requireCustomer } from "@/lib/auth";
import LogoutButton from "@/components/logout-button";

export default async function PortalLayout({ children }: { children: React.ReactNode }) {
  const user = await requireCustomer();
  if (!user) redirect("/login");
  return <main><header className="topbar"><Link className="brand" href="/portal">Omni<span>Care</span></Link><nav><Link href="/portal/orders">Đơn hàng</Link></nav><span className="persona">CUSTOMER · {user.customer?.name}</span><LogoutButton /></header>{children}</main>;
}
