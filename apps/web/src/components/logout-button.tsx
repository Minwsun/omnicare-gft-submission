"use client";

export default function LogoutButton() {
  async function logout() {
    await fetch("/api/auth/logout", { method: "POST" });
    location.href = "/login";
  }
  return <button className="logout-button" onClick={logout}>Đăng xuất</button>;
}
