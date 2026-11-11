<script lang="ts">
  import { api, apiUpload } from './api'
  import { bytes } from './fmt'
  import Unmatched from './Unmatched.svelte'
  import { nav } from './nav.svelte'

  type R = { title: string; indexer: string; category: string; size: number; seeders: number; download_url: string
    info_hash: string | null; published: string | null }

  let tab = $state<'dl' | 'unmatched'>(nav.othersTab)
  $effect(() => { nav.othersTab = tab })
  let unmatchedCount = $state<number | null>(null)
  $effect(() => { api<{ items: unknown[] }>('/library/unmatched').then((r) => (unmatchedCount = r.items.length)).catch(() => {}) })

  let q = $state('')
  let results = $state<R[]>([])
  let errors = $state<{ indexer: string; error: string }[]>([])
  let category = $state('all')
  let searching = $state(false)
  let searched = $state(false)
  let msg = $state('')
  let magnet = $state('')
  let over = $state(false)
  let done = $state<Record<string, string>>({})

  const categories = $derived([...new Set(results.map((r) => r.category).filter(Boolean))].sort())
  const shown = $derived(results.filter((r) => category === 'all' || r.category === category))

  async function search() {
    if (!q.trim()) return
    searching = true; msg = ''; category = 'all'
    try {
      const r = await api<{ results: R[]; errors: typeof errors }>(`/others/search?q=${encodeURIComponent(q)}`)
      results = r.results; errors = r.errors; searched = true
    } catch (e: any) { msg = e.message }
    searching = false
  }
  async function grab(r: R) {
    done[r.download_url] = 'Adding…'
    try {
      await api('/others/grab', 'POST', { title: r.title, download_url: r.download_url, info_hash: r.info_hash, indexer: r.indexer })
      done[r.download_url] = 'Added ✓'
    } catch (e: any) { done[r.download_url] = e.message }
  }
  async function upload(files: FileList | File[]) {
    const list = [...files].filter((f) => f.name.toLowerCase().endsWith('.torrent'))
    if (!list.length) { msg = 'Only .torrent files can be uploaded'; return }
    const form = new FormData()
    for (const f of list) form.append('files', f)
    try {
      const r = await apiUpload<{ added: { title: string }[]; failed: { file: string; error: string }[] }>('/others/upload', form)
      msg = [r.added.length ? `Added ${r.added.length}: ${r.added.map((a) => a.title).join(', ')}` : '',
        ...r.failed.map((f) => `${f.file}: ${f.error}`)].filter(Boolean).join(' · ')
    } catch (e: any) { msg = e.message }
  }
  function drop(e: DragEvent) {
    e.preventDefault(); over = false
    if (e.dataTransfer?.files.length) upload(e.dataTransfer.files)
  }
  async function addMagnet() {
    if (!magnet.trim()) return
    try { const r = await api<{ title: string }>('/others/magnet', 'POST', { magnet: magnet.trim() }); msg = `Added ${r.title}`; magnet = '' }
    catch (e: any) { msg = e.message }
  }
</script>

<div class="tabs">
  <button class:on={tab === 'dl'} onclick={() => (tab = 'dl')}>Downloads &amp; search</button>
  <button class:on={tab === 'unmatched'} onclick={() => (tab = 'unmatched')}>Unmatched folders{unmatchedCount !== null ? ` (${unmatchedCount})` : ''}</button>
</div>

{#if tab === 'unmatched'}
  <Unmatched />
{:else}
<p>Anything that isn't a movie or series: apps, games, books, music… Downloads go straight to the download folder and are
  <b>left exactly as they arrive</b> – nothing is renamed, imported or sorted. When seeding is done the torrent is removed but the files stay.</p>

<div class="drop" class:over role="presentation" ondragover={(e) => { e.preventDefault(); over = true }} ondragleave={() => (over = false)} ondrop={drop}>
  <b>Drop .torrent files here</b> or
  <label class="pick">choose files<input type="file" accept=".torrent" multiple onchange={(e) => e.currentTarget.files && upload(e.currentTarget.files)} hidden /></label>
</div>
<form class="mag" onsubmit={(e) => { e.preventDefault(); addMagnet() }}>
  <input placeholder="…or paste a magnet link" bind:value={magnet} />
  <button>Add magnet</button>
</form>
{#if msg}<p class="msg">{msg}</p>{/if}

<h3>Search your trackers</h3>
<form class="mag" onsubmit={(e) => { e.preventDefault(); search() }}>
  <input placeholder="Search for apps, games, books…" bind:value={q} />
  {#if categories.length}<select bind:value={category}><option value="all">All categories</option>{#each categories as c}<option value={c}>{c}</option>{/each}</select>{/if}
  <button disabled={searching}>{searching ? 'Searching…' : 'Search'}</button>
</form>
{#each errors as e}<p class="err">{e.indexer}: {e.error}</p>{/each}
{#if searched && shown.length === 0}<p>No results.</p>{/if}
<table>
  <tbody>
    {#each shown as r (r.download_url)}
      <tr>
        <td>{r.title}<br /><small>{r.indexer}{r.category ? ` · ${r.category}` : ''}{r.published ? ` · ${r.published.slice(0, 10)}` : ''}</small></td>
        <td>{bytes(r.size)}</td><td>{r.seeders}↑</td>
        <td>{#if done[r.download_url]}<small>{done[r.download_url]}</small>{:else}<button onclick={() => grab(r)}>Download</button>{/if}</td>
      </tr>
    {/each}
  </tbody>
</table>
{/if}

<style>
  .tabs { display: flex; gap: .4rem; margin-bottom: 1rem; } .tabs button { background: #2b3340; color: inherit; } .tabs button.on { background: #3b6fd8; color: #fff; }
  .drop { border: 2px dashed #3a4556; border-radius: 10px; padding: 1.4rem; text-align: center; margin: .8rem 0; transition: .15s; }
  .drop.over { border-color: #3b6fd8; background: #1d2a44; }
  .pick { color: #6ea0ff; cursor: pointer; text-decoration: underline; }
  .mag { display: flex; gap: .5rem; margin: .5rem 0; } .mag input { flex: 1; padding: .45rem; } select { padding: .4rem; }
  td { padding: .4rem; border-bottom: 1px solid #2b3340; font-size: .88rem; vertical-align: top; word-break: break-all; }
  button { background: #3b6fd8; color: #fff; border: 0; border-radius: 5px; padding: .35rem .8rem; cursor: pointer; }
  .msg { background: #1c2128; padding: .5rem .8rem; border-radius: 6px; } .err { color: #f66; }
</style>
