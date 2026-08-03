"use client";

import { FormEvent, useState } from "react";

export default function LoginPage() {
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");
    const form = new FormData(event.currentTarget);
    const response = await fetch("/api/auth/login", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ email: form.get("email"), password: form.get("password") }) });
    const data = await response.json();
    if (!response.ok) {
      setError(data.error === "LOGIN_RATE_LIMITED" ? "Đăng nhập bị tạm khóa. Thử lại sau 15 phút." : "Email hoặc mật khẩu không đúng.");
      setLoading(false);
      return;
    }
    location.href = data.redirectTo;
  }
  return <main className="login-page"><form className="login-card" onSubmit={submit}><p className="eyebrow">OMNICARE ACCESS</p><h1>Đăng nhập</h1><label>Email<input name="email" type="email" required autoComplete="email" /></label><label>Mật khẩu<input name="password" type="password" required autoComplete="current-password" /></label>{error && <p className="form-error">{error}</p>}<button disabled={loading}>{loading ? "Đang xác minh…" : "Đăng nhập"}</button></form></main>;
}
