import type { MetadataRoute } from "next";
const routes=["", "/quem-somos", "/participe", "/movimento-7", "/loja", "/leilao", "/parceiros", "/contato", "/privacidade", "/termos-de-servico", "/acessibilidade", "/saude"];
export default function sitemap(): MetadataRoute.Sitemap { return routes.map(route => ({ url: `https://movimento7.com.br${route}`, changeFrequency: route === "" ? "weekly" : "monthly", priority: route === "" ? 1 : .7 })); }
