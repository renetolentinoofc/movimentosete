export type ApiError = { code: string; message: string; fields: Record<string, string[]> };
export type Envelope<T> = { data: T | null; meta: Record<string, unknown>; error: ApiError | null; request_id: string | null };

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<Envelope<T>> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers }
  });
  const payload = await response.json() as Envelope<T>;
  if (!response.ok && !payload.error) throw new Error("Resposta inválida da API");
  return payload;
}

export function brl(cents: number): string {
  return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(cents / 100);
}
