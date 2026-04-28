"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { register } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

export default function RegisterPage() {
  const router = useRouter();
  const { refresh } = useAuth();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    if (password.length < 6) {
      setErr("密码至少 6 位");
      return;
    }
    setBusy(true);
    try {
      await register(email.trim(), password, name.trim() || undefined);
      await refresh();
      router.push("/");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "注册失败");
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
          注册新账号
        </h1>
        <label className="mb-1 block text-[12px]" style={{ color: "var(--app-text-secondary)" }}>
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
        <label className="mb-1 block text-[12px]" style={{ color: "var(--app-text-secondary)" }}>
          昵称（可选）
        </label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={120}
          className="mb-3 w-full rounded-md border px-3 py-2 text-[13px] outline-none"
          style={{
            backgroundColor: "var(--app-surface-input)",
            borderColor: "var(--app-border-subtle)",
            color: "var(--app-text-primary)",
          }}
        />
        <label className="mb-1 block text-[12px]" style={{ color: "var(--app-text-secondary)" }}>
          密码（≥6 位）
        </label>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          minLength={6}
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
          {busy ? "注册中…" : "注册并登录"}
        </button>
        <div
          className="mt-4 text-center text-[11px]"
          style={{ color: "var(--app-text-tertiary)" }}
        >
          已有账号？{" "}
          <Link
            href="/login"
            className="underline"
            style={{ color: "var(--app-accent-text-light)" }}
          >
            登录
          </Link>
        </div>
      </form>
    </main>
  );
}
