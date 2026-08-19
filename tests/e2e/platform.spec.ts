import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("home entrega conteúdo e navegação principal", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Cultura, Arte & Beleza/i })).toBeVisible();
  const about = page.getByRole("link", { name: "QUEM SOMOS" });
  if (!(await about.isVisible())) await page.getByRole("button", { name: "Abrir menu" }).click();
  await about.click();
  await expect(page).toHaveURL(/quem-somos/);
});

test("menu móvel abre, fecha por Escape e devolve foco", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  const menu = page.locator('button[aria-controls="main-nav"]');
  await menu.click();
  await expect(menu).toHaveAttribute("aria-expanded", "true");
  await page.keyboard.press("Escape");
  await expect(menu).toBeFocused();
});

test("inscrição inválida mantém formulário e mostra resumo", async ({ page }) => {
  await page.goto("/participe");
  await page.getByRole("button", { name: "ENVIAR INSCRIÇÃO" }).click();
  await expect(page.locator(".error-summary")).toContainText("Revise os campos");
  await expect(page.getByLabel("Nome completo")).toBeVisible();
});

test("login inválido não enumera conta", async ({ page }) => {
  await page.goto("/admin/login");
  await page.getByLabel("E-mail").fill("inexistente@example.test");
  await page.getByLabel("Senha").fill("senha-incorreta");
  await page.getByRole("button", { name: "ENTRAR" }).click();
  await expect(page.locator(".error-summary")).toContainText("E-mail ou senha inválidos");
});

test("loja vazia não inventa disponibilidade ou pagamento", async ({ page }) => {
  await page.goto("/loja");
  await expect(page.getByText(/Produtos aparecem aqui somente/)).toBeVisible();
  await page.goto("/checkout");
  await expect(page.getByText(/nenhum pagamento é marcado como aprovado/i)).toBeVisible();
});

test("leilão informa feature desativada", async ({ page }) => {
  await page.goto("/leilao");
  await expect(page.getByText(/Lances monetários permanecem desativados/i)).toBeVisible();
  await expect(page.getByRole("button", { name: /DAR MEU LANCE/ })).toHaveCount(0);
});

test("404 oferece caminho de retorno", async ({ page }) => {
  await page.goto("/rota-que-nao-existe");
  await expect(page.getByRole("heading", { name: /saiu do mapa/i })).toBeVisible();
  await expect(page.getByRole("link", { name: "VOLTAR AO INÍCIO" })).toBeVisible();
});

test("home não tem violações axe de impacto sério", async ({ page }) => {
  await page.goto("/");
  const results = await new AxeBuilder({ page }).analyze();
  expect(
    results.violations.filter(item => ["serious", "critical"].includes(item.impact ?? ""))
  ).toEqual([]);
});
