"use client";

import { Menu, X } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import styles from "./site-header.module.css";

const links = [
  ["/", "INÍCIO"], ["/quem-somos", "QUEM SOMOS"], ["/participe", "PARTICIPE"],
  ["/loja", "LOJA"], ["/leilao", "LEILÃO"], ["/contato", "CONTATO"]
];

export function SiteHeader() {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  const toggle = useRef<HTMLButtonElement>(null);
  const firstLink = useRef<HTMLAnchorElement>(null);
  useEffect(() => {
    if (open) firstLink.current?.focus();
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") { setOpen(false); toggle.current?.focus(); }
    };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [open]);
  return <header className={styles.header}>
    <div className={`container ${styles.bar}`}>
      <Link className={styles.brand} href="/" aria-label="Movimento 7 — início">
        <Image src="/brand/logo-movimento7.webp" alt="" width={640} height={640} priority sizes="54px" />
        <span>MOVIMENTO 7</span>
      </Link>
      <button ref={toggle} className={styles.toggle} type="button" aria-expanded={open} aria-controls="main-nav" aria-label={open ? "Fechar menu" : "Abrir menu"} onClick={() => setOpen(!open)}>
        {open ? <X aria-hidden /> : <Menu aria-hidden />}
      </button>
      <nav id="main-nav" aria-label="Principal" className={`${styles.nav} ${open ? styles.open : ""}`}>
        {links.map(([href, label], index) => <Link onClick={() => setOpen(false)} ref={index === 0 ? firstLink : undefined} key={href} href={href} aria-current={pathname === href ? "page" : undefined}>{label}</Link>)}
        <Link onClick={() => setOpen(false)} className="button" href="/participe">INSCREVA-SE</Link>
      </nav>
    </div>
  </header>;
}
