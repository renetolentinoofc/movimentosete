import type { MetadataRoute } from "next";
export default function robots(): MetadataRoute.Robots { return { rules: { userAgent: "*", allow: "/", disallow: ["/admin/", "/checkout", "/pedido/", "/api/"] }, sitemap: "https://movimento7.com.br/sitemap.xml", host: "https://movimento7.com.br" }; }
