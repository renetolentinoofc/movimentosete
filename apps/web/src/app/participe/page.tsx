import type { Metadata } from "next";
import { RegistrationForm } from "@/components/registration-form";
export const metadata: Metadata = { title: "Participe", description: "Faça parte do Movimento 7.", alternates: { canonical: "/participe" } };
export default function ParticipatePage() { return <><section className="section paper"><div className="container"><p className="eyebrow">Inscrições</p><h1>Faça parte do Movimento 7</h1><p className="lead">Escolha sua categoria e apresente seu trabalho. A inscrição só é concluída quando o servidor exibe um protocolo.</p></div></section><section className="section"><div className="container"><RegistrationForm /></div></section></>; }
