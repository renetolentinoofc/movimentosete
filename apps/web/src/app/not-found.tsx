import Link from "next/link";
export default function NotFound() { return <section className="section"><div className="container"><p className="eyebrow">Erro 404</p><h1>Essa rota saiu do mapa</h1><p className="lead">A página não existe ou ainda não foi publicada.</p><Link className="button" href="/">VOLTAR AO INÍCIO</Link></div></section>; }
