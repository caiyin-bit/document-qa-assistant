import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "文档问答助手",
  description: "PDF document QA assistant — Chinese, with page-level citations",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body className="antialiased">{children}</body>
    </html>
  );
}
