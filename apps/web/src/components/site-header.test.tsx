import { render,screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi,describe,it,expect } from "vitest";
vi.mock("next/navigation",()=>({usePathname:()=>"/"}));
import { SiteHeader } from "./site-header";
describe("SiteHeader",()=>{it("abre e fecha o menu móvel por teclado",async()=>{const user=userEvent.setup();render(<SiteHeader/>);const button=screen.getByRole("button",{name:"Abrir menu"});await user.click(button);expect(button).toHaveAttribute("aria-expanded","true");await user.keyboard("{Escape}");expect(button).toHaveAttribute("aria-expanded","false");expect(button).toHaveFocus()})});
