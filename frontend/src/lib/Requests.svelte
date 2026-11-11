<script lang="ts">
  import { api } from './api'
  import { auth } from './auth.svelte'

  type Rq = { id: number; kind: string; title: string; year: number | null; poster_url: string | null; overview: string | null
    status: string; note: string | null; user: string | null; created: string | null }
  let items = $state<Rq[]>([])
  let msg = $state('')
  const admin = $derived(!auth.user || auth.user.is_admin)

  async function load() { items = await api('/requests') }
  $effect(() => { load() })

  async function approve(r: Rq, searchNow: boolean) {
    msg = 'Adding…'
    try { await api(`/requests/${r.id}/approve`, 'POST', { search_now: searchNow }); msg = `Approved ${r.title}` } catch (e: any) { msg = e.message }
    await load()
  }
  async function deny(r: Rq) {
    const note = prompt('Reason (optional, shown to the requester)') ?? undefined
    await api(`/requests/${r.id}/deny`, 'POST', { note }); await load()
  }
  async function withdraw(r: Rq) { await api(`/requests/${r.id}`, 'DELETE'); await load() }

  const pending = $derived(items.filter((r) => r.status === 'pending'))
  const rest = $derived(items.filter((r) => r.status !== 'pending'))
</script>

{#if msg}<p class="msg">{msg}</p>{/if}
<h3>Pending ({pending.length})</h3>
{#each pending as r (r.id)}
  <div class="row">
    {#if r.poster_url}<img src={r.poster_url} alt="" loading="lazy" />{:else}<div class="noimg"></div>{/if}
    <div class="grow"><b>{r.title}</b> {r.year ?? ''} <span class="tag" class:tv={r.kind === 'series'}>{r.kind === 'series' ? 'Series' : 'Movie'}</span><br />
      <small>requested by {r.user} · {r.created?.slice(0, 10)}</small><br /><small>{r.overview?.slice(0, 160) ?? ''}</small></div>
    {#if admin}
      <button class="ok" onclick={() => approve(r, true)}>Approve &amp; search</button>
      <button onclick={() => approve(r, false)}>Approve</button>
      <button class="danger" onclick={() => deny(r)}>Deny</button>
    {:else}
      <button onclick={() => withdraw(r)}>Withdraw</button>
    {/if}
  </div>
{:else}<p>No pending requests.</p>{/each}

{#if rest.length}
  <h3>History</h3>
  {#each rest as r (r.id)}
    <div class="row slim"><span class="grow">{r.title} {r.year ?? ''} <small>· {r.user}</small></span>
      <span class="st {r.status}">{r.status === 'available' ? 'available ✓' : r.status}</span>{#if r.note}<small>“{r.note}”</small>{/if}</div>
  {/each}
{/if}

<style>
  .row { display: flex; gap: .8rem; align-items: center; background: #1c2128; padding: .5rem .7rem; border-radius: 8px; margin-bottom: .4rem; }
  .row.slim { padding: .3rem .7rem; } .grow { flex: 1; }
  img, .noimg { width: 44px; height: 66px; object-fit: cover; background: #2b3340; border-radius: 4px; }
  .tag { font-size: .7rem; padding: .05rem .4rem; border-radius: 4px; background: #2d4a7a; } .tag.tv { background: #6a3d7a; }
  .st { font-size: .75rem; padding: .1rem .5rem; border-radius: 999px; } .st.approved { background: #1f4d2e; } .st.denied { background: #6a2a2a; }
  button { background: #2b3340; color: inherit; border: 0; border-radius: 4px; padding: .3rem .7rem; cursor: pointer; }
  button.ok { background: #3b6fd8; color: #fff; } button.danger { background: #3a2226; color: #f99; }
  .msg { background: #1c2128; padding: .4rem .7rem; border-radius: 6px; }
</style>
