import type { Metadata } from "next";
import { Gallery } from "@/components/gallery";
import type { Envelope } from "@/lib/api";
export const dynamic="force-dynamic";
export const metadata:Metadata={title:"Galeria",description:"Fotos e vídeos do Movimento 7.",alternates:{canonical:"/movimento-7"}};
type Media={id:string;album:string;edition:string;category:string;type:string;url:string;title:string;caption?:string;alt:string;credit?:string;width?:number;height?:number};
async function load(){try{const response=await fetch(`${process.env.INTERNAL_API_URL??"http://127.0.0.1:5000"}/api/v1/gallery?limit=50`,{next:{revalidate:60}});return (await response.json() as Envelope<Media[]>).data??[]}catch{return []}}
export default async function GalleryPage(){return <><section className="section paper"><div className="container"><p className="eyebrow">Movimento 7</p><h1>Galeria</h1><p className="lead">Eventos, talentos e bastidores registrados com legenda, crédito e contexto.</p></div></section><section className="section"><div className="container"><Gallery items={await load()}/></div></section></>}
