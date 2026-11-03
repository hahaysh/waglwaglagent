import type { Metadata } from "next";
import "@fontsource-variable/manrope";
import "@fontsource-variable/noto-sans-kr";
import "./globals.css";

export const metadata: Metadata = {
  title: "waglwaglagent | 개인 AI 작업공간",
  description: "개인 API 키와 허용된 무료 AI 연결로 이어가는 대화",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
