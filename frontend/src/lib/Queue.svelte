<script lang="ts">
  import { api } from './api'
  import { bytes, duration, speed } from './fmt'

  type Live = { state: string; size: number; downloaded: number; uploaded: number; ratio: number; seeding_seconds: number
    down_rate: number; up_rate: number; peers: number; seeds: number; eta: number | null; paused: boolean }
  type Item = { id: number; title: string; kind: string; status: string; progress: number; error: string | null
    indexer: string | null; added: string | null; live: Live | null
    rules: { ratio: number; hours: number; mode: string } | null }

  let items = $state<Item[]>([])
  let history = $state<{ id: number; event: string; title: string; detail: string | null; date: string }[]>([])
  let msg = $state('')

  async function load() {
    items = await api('/queue')
    history = await api('/history?limit=30')
  }
  async function act(path: string, method = 'POST') {
    try { await api(path, method) } catch (e: any) { msg = e.message }
    await load()
  }
  function stop(i: Item, deleteFiles: boolean) {
    const what = deleteFiles
      ? `Stop seeding and DELETE the downloaded files for:\n${i.title}\n\n${i.kind === 'other' ? 'There is no other copy.' : '(The copy in your library is kept.)'}`
      : `Stop seeding (the files stay in the download folder):\n${i.title}`
    if (confirm(what)) act(`/queue/${i.id}?delete_files=${deleteFiles}`, 'DELETE')
  }

  $effect(() => {
    load()
    const t = setInterval(load, 3000)
    return () => clearInterval(t)
  })

  const downloading = $derived(items.filter((i) => ['downloading', 'completed', 'importing'].includes(i.status)))
  const seeding = $derived(items.filter((i) => i.status === 'seeding'))
  const failed = $derived(items.filter((i) => i.status === 'failed'))
  const totals = $derived({
    up: items.reduce((a, i) => a + (i.live?.uploaded ?? 0), 0),
    upRate: items.reduce((a, i) => a + (i.live?.up_rate ?? 0), 0),
    downRate: items.reduce((a, i) => a + (i.live?.down_rate ?? 0), 0),
  })

  const label: Record<string, string> = { downloading: 'Downloading', completed: 'Finished – waiting to import',
    importing: 'Importing (copying / unpacking)…', seeding: 'Seeding', failed: 'Failed' }
  const pct = (a: number, b: number) => Math.min(100, Math.max(0, b ? (a / b) * 100 : 0))
</script>

<div class="summary">
  <div><b>{items.length}</b> torrents</div>
  <div>↓ <b>{speed(totals.downRate)}</b></div>
  <div>↑ <b>{speed(totals.upRate)}</b></div>
  <div>Uploaded (active): <b>{bytes(totals.up)}</b></div>
</div>
{#if msg}<p class="err">{msg}</p>{/if}

{#snippet card(i: Item)}
  <div class="card" class:bad={i.status === 'failed'}>
    <div class="head">
      <div class="title">{i.title}</div>
      {#if i.kind === 'other'}<span class="chip other">Other · no import</span>{/if}
      <span class="chip {i.status}">{i.live?.paused ? 'Paused' : label[i.status] ?? i.status}</span>
    </div>
    {#if i.error}<p class="err">{i.error}</p>{/if}
    {#if i.status !== 'seeding' && i.status !== 'failed'}
      <div class="bar"><div class="fill" style={`width:${i.progress * 100}%`}></div></div>
    {/if}
    {#if i.live}
      <div class="stats">
        <div><small>Size</small>{bytes(i.live.size)}</div>
        <div><small>Downloaded</small>{bytes(i.live.downloaded)}</div>
        <div><small>Uploaded</small><b>{bytes(i.live.uploaded)}</b></div>
        <div><small>Ratio</small><b>{i.live.ratio.toFixed(2)}</b></div>
        <div><small>Seeding time</small>{duration(i.live.seeding_seconds)}</div>
        <div><small>↓ speed</small>{speed(i.live.down_rate)}</div>
        <div><small>↑ speed</small>{speed(i.live.up_rate)}</div>
        <div><small>Peers / seeds</small>{i.live.peers} / {i.live.seeds}</div>
        {#if i.status === 'downloading'}<div><small>ETA</small>{duration(i.live.eta)}</div>{/if}
        {#if i.indexer}<div><small>Tracker</small>{i.indexer}</div>{/if}
      </div>
    {/if}
    {#if i.status === 'seeding' && i.rules && i.live}
      <div class="rule">
        <small>Auto-cleanup when ratio ≥ {i.rules.ratio} {i.rules.mode === 'both' ? 'AND' : 'OR'} {i.rules.hours} h of seeding</small>
        <div class="two">
          <div><div class="bar thin"><div class="fill r" style={`width:${pct(i.live.ratio, i.rules.ratio)}%`}></div></div><small>ratio {i.live.ratio.toFixed(2)} / {i.rules.ratio}</small></div>
          <div><div class="bar thin"><div class="fill t" style={`width:${pct(i.live.seeding_seconds, i.rules.hours * 3600)}%`}></div></div><small>{duration(i.live.seeding_seconds)} / {i.rules.hours} h</small></div>
        </div>
      </div>
    {/if}
    <div class="btns">
      {#if i.live && ['downloading', 'seeding'].includes(i.status)}
        {#if i.live.paused}<button onclick={() => act(`/queue/${i.id}/resume`)}>▶ Resume</button>
        {:else}<button onclick={() => act(`/queue/${i.id}/pause`)}>⏸ Pause</button>{/if}
      {/if}
      {#if i.status === 'seeding'}
        {#if i.kind === 'other'}<button onclick={() => stop(i, false)}>Stop seeding (keep files)</button>{/if}
        <button class="danger" onclick={() => stop(i, true)}>Stop seeding &amp; delete files</button>
      {/if}
      {#if i.status !== 'seeding'}
        <button onclick={() => act(`/queue/${i.id}?blocklist=false`, 'DELETE')}>Remove</button>
        <button onclick={() => act(`/queue/${i.id}?blocklist=true`, 'DELETE')}>Remove &amp; blocklist</button>
      {/if}
    </div>
  </div>
{/snippet}

<h3>Downloading</h3>
{#each downloading as i (i.id)}{@render card(i)}{:else}<p>Nothing downloading.</p>{/each}
<h3>Seeding</h3>
{#each seeding as i (i.id)}{@render card(i)}{:else}<p>Nothing seeding.</p>{/each}
{#if failed.length}<h3>Failed</h3>{#each failed as i (i.id)}{@render card(i)}{/each}{/if}

<h3>History</h3>
<table><tbody>
  {#each history as h (h.id)}
    <tr><td>{h.date.slice(0, 16).replace('T', ' ')}</td><td>{h.event === 'would_grab' ? '🧪 would grab (dry run)' : h.event}</td><td>{h.title}<br /><small>{h.detail ?? ''}</small></td></tr>
  {/each}
</tbody></table>

<style>
  .summary { display: flex; gap: 2rem; background: #1c2128; padding: .6rem 1rem; border-radius: 8px; margin-bottom: 1rem; flex-wrap: wrap; }
  .card { background: #1c2128; border-radius: 8px; padding: .8rem 1rem; margin-bottom: .6rem; }
  .card.bad { border-left: 3px solid #f66; }
  .head { display: flex; gap: 1rem; align-items: flex-start; }
  .title { flex: 1; word-break: break-all; font-weight: 600; }
  .chip { font-size: .75rem; padding: .15rem .55rem; border-radius: 999px; background: #2b3340; white-space: nowrap; }
  .chip.other { background: #4a3d6a; }
  .chip.seeding { background: #1f4d2e; } .chip.downloading { background: #2d4a7a; } .chip.importing, .chip.completed { background: #6a5a1f; } .chip.failed { background: #6a2a2a; }
  .bar { height: 8px; background: #2b3340; border-radius: 4px; margin: .5rem 0; overflow: hidden; }
  .bar.thin { height: 5px; margin: .25rem 0; }
  .fill { height: 100%; background: #3b6fd8; transition: width .6s; } .fill.r { background: #3fb950; } .fill.t { background: #c9a227; }
  .stats { display: grid; grid-template-columns: repeat(auto-fill, minmax(110px, 1fr)); gap: .5rem; font-size: .85rem; margin: .4rem 0; }
  .stats small { display: block; opacity: .6; font-size: .7rem; text-transform: uppercase; }
  .rule { margin: .5rem 0; } .two { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
  small { opacity: .75; }
  .btns { display: flex; gap: .4rem; flex-wrap: wrap; margin-top: .4rem; }
  button { background: #2b3340; color: inherit; border: 0; border-radius: 4px; padding: .3rem .7rem; cursor: pointer; }
  button.danger { background: #3a2226; color: #f99; }
  td { padding: .25rem .6rem; font-size: .85rem; vertical-align: top; } .err { color: #f66; }
</style>
