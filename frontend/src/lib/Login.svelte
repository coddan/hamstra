<script lang="ts">
  import { auth, refreshAuth } from './auth.svelte'

  let username = $state('')
  let password = $state('')
  let error = $state('')

  async function submit() {
    error = ''
    const res = await fetch(auth.setupRequired ? '/api/v1/auth/setup' : '/api/v1/auth/login', {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ username, password }),
    })
    if (!res.ok) { error = (await res.json().catch(() => ({}))).detail ?? 'Failed'; return }
    await refreshAuth()
    location.reload()
  }
</script>

<div class="wrap">
  <form onsubmit={(e) => { e.preventDefault(); submit() }}>
    <h2>🐹 Hamstra</h2>
    <p>{auth.setupRequired ? 'First run: create the admin account' : 'Sign in'}</p>
    <input placeholder="Username" bind:value={username} autocomplete="username" required />
    <input type="password" placeholder="Password" bind:value={password}
      autocomplete={auth.setupRequired ? 'new-password' : 'current-password'} required />
    {#if error}<p class="err">{error}</p>{/if}
    <button>{auth.setupRequired ? 'Create account' : 'Sign in'}</button>
  </form>
</div>

<style>
  .wrap { min-height: 100vh; display: flex; align-items: center; justify-content: center; }
  form { background: #1c2128; padding: 2rem; border-radius: 10px; display: flex; flex-direction: column; gap: .6rem; width: 18rem; }
  input { padding: .5rem; }
  button { background: #3b6fd8; color: white; border: 0; border-radius: 6px; padding: .55rem; cursor: pointer; }
  .err { color: #f66; margin: 0; }
  h2 { margin: 0; }
</style>
