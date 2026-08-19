import type { Metadata } from "next";
import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";
import "./globals.css";

const siteUrl = process.env.NEXT_PUBLIC_SITE_URL ?? "https://movimento7.com.br";
export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: { default: "Movimento 7 — Cultura, Arte & Beleza", template: "%s | Movimento 7" },
  description: "Projeto cultural que conecta arte, cultura urbana, beleza, música, moda, esporte e empreendedorismo.",
  alternates: { canonical: "/" },
  openGraph: { type: "website", locale: "pt_BR", siteName: "Movimento 7", images: [{ url: "/brand/hero/movimento7-grafite.webp", width: 1600, height: 686 }] },
  twitter: { card: "summary_large_image" }
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="pt-BR"><body><a className="skip-link" href="#conteudo">Pular para o conteúdo</a><SiteHeader /><main id="conteudo">{children}</main><SiteFooter /></body></html>;
}
