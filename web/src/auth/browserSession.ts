export type BrowserSession = {
  user: { id: string; email: string; name: string };
  deviceCount: number;
};

export async function browserSession(): Promise<BrowserSession | null> {
  const response = await fetch('/api/auth/session', { credentials: 'same-origin' });
  if (response.status === 401) return null;
  if (!response.ok) throw new Error('Unable to check your account session.');
  return response.json() as Promise<BrowserSession>;
}
