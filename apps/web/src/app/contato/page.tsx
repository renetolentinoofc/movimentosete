import type { Metadata } from "next";
import { ContactForm } from "@/components/contact-form";
export const metadata: Metadata={title:"Contato",alternates:{canonical:"/contato"}};
export default function ContactPage(){return <><section className="section paper"><div className="container"><p className="eyebrow">Contato</p><h1>Fale com o Movimento</h1><p className="lead">Os canais oficiais aparecem aqui quando forem configurados no painel. O formulário abaixo já gera um protocolo seguro.</p></div></section><section className="section"><div className="container"><ContactForm /></div></section></>}
