import type { Metadata } from "next";
import Script from "next/script";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import "./globals.css";

export const metadata: Metadata = {
  title: "文档问答助手",
  description: "PDF document QA assistant — Chinese, with page-level citations",
};

// This runs in the browser BEFORE React hydrates, so the first paint already
// has the correct data-theme on <html>. Without this, the page would briefly
// render in :root light tokens before useTheme applies the stored preference.
//
// Resolution order matches spec §6 acceptance criteria + useTheme hook:
//   1. valid localStorage value
//   2. prefers-color-scheme query (when matchMedia is supported)
//   3. brand default 'dark' (when matchMedia is missing — older browsers)
const ANTI_FOUC = `
try {
  var t = localStorage.getItem('docqa.theme');
  if (t !== 'dark' && t !== 'light') {
    if (window.matchMedia) {
      t = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    } else {
      t = 'dark';
    }
  }
  document.documentElement.dataset.theme = t;
} catch(e) {}
`;

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="zh-CN"
      data-theme="dark"
      className={`${GeistSans.variable} ${GeistMono.variable}`}
    >
      <head>
        <Script id="anti-fouc" strategy="beforeInteractive">
          {ANTI_FOUC}
        </Script>
      </head>
      <body className="antialiased font-sans">{children}</body>
    </html>
  );
}
