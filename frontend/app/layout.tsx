import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "TipMind — Your Autonomous Fan Agent",
  description: "AI-powered crypto tipping for video creators",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={inter.className} style={{ backgroundColor: "#0a0e1a", minHeight: "100vh" }}>
        {children}
      </body>
    </html>
  );
}
