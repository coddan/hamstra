<script lang="ts">
  import { api } from './lib/api'
  import Library from './lib/Library.svelte'
  import Settings from './lib/Settings.svelte'
  import Queue from './lib/Queue.svelte'
  import Others from './lib/Others.svelte'
  import System from './lib/System.svelte'
  import Music from './lib/Music.svelte'
  import Requests from './lib/Requests.svelte'
  import Calendar from './lib/Calendar.svelte'
  import Login from './lib/Login.svelte'
  import { auth, refreshAuth } from './lib/auth.svelte'
  import { nav } from './lib/nav.svelte'

  type Status = { version: string; roots: Record<string, string>; tmdb_configured: boolean }
  type Root = { id: number; path: string; kind: string; exists: boolean }

  const baseAdmin = ['dashboard', 'movies', 'series', 'music', 'others', 'queue', 'system', 'settings']
  const baseUser = ['dashboard', 'movies', 'series', 'queue', 'settings']
  let pendingRequests = $state(0)
  let unlinked = $state(0)
  const isAdmin = $derived(!auth.user || auth.user.is_admin)
  // Requests only appear when they matter: an admin has something to approve, or a normal user has made requests
  const pages = $derived([...(isAdmin ? baseAdmin : baseUser), ...(pendingRequests > 0 || (!isAdmin && auth.user) ? ['requests'] : [])])

  $effect(() => {
    if (auth.loading || auth.needsLogin) return
    const load = () => api<{ status: string }[]>('/requests').then((r) => (pendingRequests = isAdmin ? r.filter((x) => x.status === 'pending').length : r.length)).catch(() => {})
    load()
    if (isAdmin) api<{ items: unknown[] }>('/library/unmatched').then((r) => (unlinked = r.items.length)).catch(() => {})
    const t = setInterval(load, 60000)
    return () => clearInterval(t)
  })

  let status = $state<Status | null>(null)
  let roots = $state<Root[]>([])
  let error = $state('')
  let vpn = $state<{ configured: boolean; interface: string | null; up: boolean | null } | null>(null)

  async function logout() {
    await fetch('/api/v1/auth/logout', { method: 'POST' })
    location.reload()
  }

  refreshAuth()

  $effect(() => {
    if (auth.loading || auth.needsLogin) return
    Promise.all([api<Status>('/system/status'), api<Root[]>('/system/rootfolders'), api<typeof vpn>('/system/vpn')])
      .then(([s, r, v]) => { status = s; roots = r; vpn = v })
      .catch((e) => (error = e.message))
  })
</script>

{#if auth.loading}
  <p style="padding:2rem">Loading…</p>
{:else if auth.needsLogin}
  <Login />
{:else}
<div class="layout">
  <nav>
    <h2>🐹 Hamstra</h2>
    {#each pages as p}
      <button class:active={nav.page === p} onclick={() => (nav.page = p)}>{p}</button>
    {/each}
    <div class="spacer"></div>
    {#if auth.user}<small>{auth.user.username}</small><button onclick={logout}>Sign out</button>{/if}
  </nav>
  <main>
    <h1>{nav.page}</h1>
    {#if error}<p class="err">{error}</p>{/if}
    {#if nav.page === 'dashboard' && status}
      <p>Version {status.version} · TMDB {status.tmdb_configured ? 'configured' : 'not configured'}</p>
      {#if vpn?.configured}
        <p class:err={!vpn.up} class:ok={vpn.up}>VPN {vpn.interface}: {vpn.up ? 'up' : 'DOWN – downloads paused'}</p>
      {:else}
        <p>VPN guard: off (set an interface under Settings → Torrent client)</p>
      {/if}
      {#if isAdmin && unlinked > 0}
        <div class="notice">📂 <b>{unlinked}</b> folders in your media folders are not linked to a title yet.
          <button onclick={() => { nav.othersTab = 'unmatched'; nav.page = 'others' }}>Review them</button></div>
      {/if}
      <h3>Calendar</h3>
      <Calendar />
      <h3>Root folders</h3>
      <ul>
        {#each roots as r}
          <li>{r.kind}: {r.path} {r.exists ? '✓' : '✗ missing'}</li>
        {/each}
      </ul>
    {:else if nav.page === 'movies' || nav.page === 'series'}
      <Library kind={nav.page as 'movies' | 'series'} />
    {:else if nav.page === 'music'}
      <Music />
    {:else if nav.page === 'requests'}
      <Requests />
    {:else if nav.page === 'system'}
      <System />
    {:else if nav.page === 'others'}
      <Others />
    {:else if nav.page === 'queue'}
      <Queue />
    {:else if nav.page === 'settings'}
      <Settings />
    {:else if nav.page !== 'dashboard'}
      <p>Coming soon.</p>
    {/if}
  </main>
</div>
{/if}

<style>
  .layout { display: flex; min-height: 100vh; }
  nav { width: 180px; background: #1c2128; padding: 1rem; display: flex; flex-direction: column; gap: .25rem; }
  nav button { background: none; border: 0; color: inherit; text-align: left; padding: .5rem; border-radius: 6px; text-transform: capitalize; cursor: pointer; }
  nav button.active, nav button:hover { background: #2b3340; }
  main { padding: 1.5rem; flex: 1; }
  h1 { text-transform: capitalize; margin-top: 0; }
  .err { color: #f66; }
  .notice { background: #1c2128; border-left: 3px solid #c9a227; padding: .6rem .9rem; border-radius: 6px; margin: .8rem 0; display: flex; gap: .8rem; align-items: center; }
  .notice button { background: #3b6fd8; color: #fff; border: 0; border-radius: 5px; padding: .35rem .8rem; cursor: pointer; }
  .ok { color: #3fb950; }
  .spacer { flex: 1; }
</style>
