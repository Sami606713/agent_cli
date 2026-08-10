import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Agent",
  description: "A LangChain agent",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
