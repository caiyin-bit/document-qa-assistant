"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { login } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

export default function LoginPage() {
  const router = useRouter();
  const { me, loading: authLoading, refresh } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Already-real-logged-in users bypass the form. is_demo doesn't
  // count — the home page treats it as "not logged in".
  useEffect(() => {
    if (!authLoading && me && !me.is_demo) {
      router.replace("/");
    }
  }, [authLoading, me, router]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      await login(email.trim(), password);
      await refresh();
      router.push("/");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "登录失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main
      className="flex h-screen w-screen items-center justify-center"
      style={{ backgroundColor: "var(--app-bg)" }}
    >
      <form
        onSubmit={onSubmit}
        className="w-[360px] rounded-lg border p-6"
        style={{
          backgroundColor: "var(--app-surface-elevated)",
          borderColor: "var(--app-border-subtle)",
        }}
      >
        <h1
          className="mb-4 text-center text-[18px] font-semibold"
          style={{ color: "var(--app-text-primary)" }}
        >
          登录文档问答助手
        </h1>
        <label
          className="mb-1 block text-[12px]"
          style={{ color: "var(--app-text-secondary)" }}
        >
          邮箱
        </label>
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          autoFocus
          required
          className="mb-3 w-full rounded-md border px-3 py-2 text-[13px] outline-none"
          style={{
            backgroundColor: "var(--app-surface-input)",
            borderColor: "var(--app-border-subtle)",
            color: "var(--app-text-primary)",
          }}
        />
        <label
          className="mb-1 block text-[12px]"
          style={{ color: "var(--app-text-secondary)" }}
        >
          密码
        </label>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          className="mb-3 w-full rounded-md border px-3 py-2 text-[13px] outline-none"
          style={{
            backgroundColor: "var(--app-surface-input)",
            borderColor: "var(--app-border-subtle)",
            color: "var(--app-text-primary)",
          }}
        />
        {err && (
          <div
            className="mb-3 rounded-md border px-3 py-2 text-[12px]"
            style={{
              backgroundColor: "var(--app-status-err-bg)",
              borderColor: "var(--app-status-err-fg)",
              color: "var(--app-status-err-fg)",
            }}
          >
            {err}
          </div>
        )}
        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-md px-3 py-2 text-[13px] font-medium transition disabled:opacity-50"
          style={{
            backgroundColor: "var(--app-accent)",
            color: "var(--app-text-on-accent)",
          }}
        >
          {busy ? "登录中…" : "登录"}
        </button>
        <div
          className="mt-4 text-center text-[11px]"
          style={{ color: "var(--app-text-tertiary)" }}
        >
          还没有账号？{" "}
          <Link
            href="/register"
            className="underline"
            style={{ color: "var(--app-accent-text-light)" }}
          >
            注册
          </Link>
        </div>
      </form>
    </main>
  );
}
