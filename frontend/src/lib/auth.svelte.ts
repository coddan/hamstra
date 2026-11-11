export const auth = $state({
  loading: true,
  needsLogin: false,
  setupRequired: false,
  user: null as { id: number; username: string; is_admin: boolean } | null,
})

export async function refreshAuth() {
  const res = await fetch('/api/v1/auth/status')
  const s = await res.json()
  auth.setupRequired = s.setup_required
  auth.user = s.user
  auth.needsLogin = !s.authenticated && !s.setup_required
  auth.loading = false
}
