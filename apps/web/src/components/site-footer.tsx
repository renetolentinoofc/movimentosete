import Link from "next/link";

export function SiteFooter() {
  return <footer className="section" style={{ borderTop: "1px solid var(--color-border)" }}>
    <div className="container grid cards">
      <div><p className="eyebrow">Movimento 7</p><p className="muted">Cultura, arte, beleza e oportunidades em movimento.</p></div>
      <nav aria-label="Institucional"><h2 style={{ fontSize: "1.4rem" }}>Informações</h2><p><Link href="/movimento-7">Galeria</Link></p><p><Link href="/parceiros">Parceiros</Link></p><p><Link href="/acessibilidade">Acessibilidade</Link></p></nav>
      <nav aria-label="Legal"><h2 style={{ fontSize: "1.4rem" }}>Transparência</h2><p><Link href="/privacidade">Privacidade</Link></p><p><Link href="/termos-de-servico">Termos</Link></p><p><Link href="/saude">Status do serviço</Link></p></nav>
    </div>
  </footer>;
}
