"use client";

import { FormEvent, useState } from "react";
import { LockKeyhole, LogIn } from "lucide-react";

export default function LoginPage() {
  const [username, setUsername] = useState("hendo420");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      const response = await fetch("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username, password }) });
      const payload = await response.json() as { error?: string };
      if (!response.ok) throw new Error(payload.error ?? "Login failed.");
      window.location.assign("/");
    } catch (loginError) {
      setError(loginError instanceof Error ? loginError.message : "Login failed.");
    } finally {
      setSubmitting(false);
    }
  }

  return <main className="flex min-h-screen items-center justify-center bg-[#070a0f] p-4 text-[#e6edf5]">
    <form onSubmit={submit} className="w-full max-w-sm border border-[#223044] bg-[#0d131c] p-6 shadow-2xl">
      <div className="flex items-center gap-3"><span className="flex h-11 w-11 items-center justify-center border border-[#21d4fd]/40 bg-[#21d4fd]/10 text-[#21d4fd]"><LockKeyhole className="h-5 w-5" /></span><div><h1 className="text-lg font-semibold">GPU45 Appliance</h1><p className="text-xs text-[#8a98aa]">Administrative console</p></div></div>
      <label className="mt-6 block text-xs font-medium text-[#8a98aa]" htmlFor="username">Username</label>
      <input id="username" autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} className="mt-2 w-full border border-[#223044] bg-[#070a0f] px-3 py-2.5 outline-none focus:border-[#21d4fd]" />
      <label className="mt-4 block text-xs font-medium text-[#8a98aa]" htmlFor="password">Password</label>
      <input id="password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} className="mt-2 w-full border border-[#223044] bg-[#070a0f] px-3 py-2.5 outline-none focus:border-[#21d4fd]" />
      {error ? <p role="alert" className="mt-3 border border-[#fb4b6b]/30 bg-[#fb4b6b]/10 p-2 text-sm text-[#fb4b6b]">{error}</p> : null}
      <button disabled={submitting} className="mt-5 flex w-full items-center justify-center gap-2 bg-[#21d4fd] px-4 py-2.5 font-semibold text-[#070a0f] disabled:opacity-60"><LogIn className="h-4 w-4" />{submitting ? "Signing in" : "Sign in"}</button>
    </form>
  </main>;
}
