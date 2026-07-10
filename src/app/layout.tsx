import type { Metadata } from "next";
import { IBM_Plex_Mono, Space_Grotesk } from "next/font/google";
import { AppChrome } from "@/components/app-chrome";
import { getApplianceVersion } from "@/lib/version";
import "./globals.css";
import { collectLiveTelemetry } from "@/lib/live-telemetry";

const spaceGrotesk = Space_Grotesk({
  variable: "--font-sans",
  subsets: ["latin"],
});

const ibmMono = IBM_Plex_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

export const metadata: Metadata = {
  title: "GPU45 Appliance",
  description: "Local LLM provider appliance for monitoring, model control, benchmarks, and fan management.",
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const initialTelemetry = await collectLiveTelemetry();
  return (
    <html lang="en" className={`${spaceGrotesk.variable} ${ibmMono.variable} h-full antialiased`}>
      <body className="min-h-full">
        <AppChrome version={getApplianceVersion()} initialTelemetry={initialTelemetry}>{children}</AppChrome>
      </body>
    </html>
  );
}

