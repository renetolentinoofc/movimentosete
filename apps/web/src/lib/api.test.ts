import { describe,expect,it } from "vitest";
import { brl } from "./api";
describe("brl",()=>{it("formata centavos sem float no contrato",()=>{expect(brl(10000)).toContain("100,00")})});
