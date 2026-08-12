import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import styles from "./page.module.css";

export const metadata: Metadata = { alternates: { canonical: "/" } };
const categories = ["Barbeiro", "MC", "Artista", "Trancista", "Skatista", "Grafiteiro", "Marca / Moda", "Empreendedor", "DJ", "Gastronomia", "Projeto social"];
const partners = [
  ["df-refrigeracao.webp", "Logo da DF Refrigeração"], ["baianao-carnes.webp", "Logo do Baianão Carnes"],
  ["acai-do-boy.webp", "Logo do Açaí do Boy"], ["garagem-dos-antigos.webp", "Logo da Garagem dos Antigos"]
];

export default function Home() {
  const organization = { "@context": "https://schema.org", "@type": "Organization", name: "Movimento 7", url: "https://movimento7.com.br", logo: "https://movimento7.com.br/brand/logo-movimento7.webp" };
  return <>
    <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(organization) }} />
    <section className={styles.hero} aria-labelledby="hero-title"><div className={`container ${styles.heroContent}`}>
      <p className="eyebrow">Movimento 7</p><h1 id="hero-title">Cultura, <span>Arte</span> & Beleza</h1>
      <p className="lead">Um projeto cultural que apresenta talentos, empreendedores e iniciativas que movimentam a cidade.</p>
      <div className={styles.actions}><Link className="button" href="/participe">QUERO PARTICIPAR</Link><Link className="button secondary" href="/loja">CONHEÇA A COLEÇÃO</Link></div>
    </div></section>
    <section className="section paper"><div className="container"><p className="eyebrow">Quem somos</p><h2>Talento encontra espaço</h2><p className="lead">Conectamos arte, cultura urbana, beleza, música, moda, esporte e empreendedorismo, criando espaço para talentos, oportunidades e novas experiências.</p><Link className="button" href="/quem-somos">CONHEÇA O MOVIMENTO</Link></div></section>
    <section className="section"><div className="container"><p className="eyebrow">Participe</p><h2>Seu corre faz parte</h2><div className="grid cards">{categories.map((name, index) => <Link className={`card ${styles.category}`} style={{ "--accent": ["var(--color-purple)", "var(--color-orange)", "var(--color-blue)", "var(--color-magenta)"][index % 4] } as React.CSSProperties} key={name} href={`/participe?categoria=${encodeURIComponent(name.toLowerCase())}`}><strong>{name}</strong></Link>)}</div></div></section>
    <section className="section"><div className="container"><p className="eyebrow">Próxima edição</p><h2>O próximo encontro</h2><div className="empty"><p>A data, o local e a abertura das inscrições aparecerão aqui assim que a próxima edição for publicada pela produção.</p></div></div></section>
    <section className="section paper"><div className="container"><p className="eyebrow">Coleção limitada</p><h2>Vista o Movimento</h2><p className="lead">Colecao limitada de streetwear. Estoque e disponibilidade são exibidos somente após cadastro e publicação.</p><Link className="button" href="/loja">VER A LOJA</Link></div></section>
    <section className="section"><div className="container"><p className="eyebrow">Galeria</p><h2>Memória em movimento</h2><div className="empty">Fotos e vídeos publicados pela produção aparecerão nesta seleção.</div><p><Link className="button secondary" href="/movimento-7">ABRIR GALERIA</Link></p></div></section>
    <section className="section"><div className="container"><p className="eyebrow">Parceiros iniciais</p><h2>Quem fortalece o movimento</h2><div className="grid cards">{partners.map(([file, alt]) => <div className={`card ${styles.partner}`} key={file}><Image src={`/brand/partners/${file}`} alt={alt} width={520} height={520} sizes="(max-width: 768px) 80vw, 20vw" /></div>)}</div><p><Link className="button" href="/parceiros">QUERO SER PARCEIRO</Link></p></div></section>
  </>;
}
