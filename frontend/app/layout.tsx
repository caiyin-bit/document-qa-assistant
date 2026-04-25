import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "保险经纪助手",
  description: "MVP demo",
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
