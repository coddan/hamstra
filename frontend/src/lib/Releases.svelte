<script lang="ts">
  import { api, apiUpload, type Release } from './api'

  let { path, grabBody, onclose }: { path: string; grabBody: Record<string, number>; onclose: () => void } = $props()
  let releases = $state<Release[]>([])
  let errors = $state<{ indexer: string; error: string }[]>([])
  let loading = $state(true)
  let msg = $state('')
  let magnet = $state('')
  let showRejected = $state(false)
  let sort = $state('score')

  $effect(() => {
    api<{ releases: Release[]; errors: typeof errors }>(path)
      .then((r) => { releases = r.releases; errors = r.errors })
      .catch((e) => (msg = e.message))
      .finally(() => (loading = false))
  })

  async function grab(r: Release) {
    try {
      await api('/grab', 'POST', { title: r.title, download_url: r.download_url, info_hash: r.info_hash, indexer: r.indexer, ...grabBody })
      msg = `Sent ${r.title}`
    } catch (e: any) { msg = e.message }
  }
  async function uploadFile(files: FileList | null) {
    if (!files?.length) return
    const form = new FormData()
    form.append('file', files[0])
    for (const [k, v] of Object.entries(grabBody)) form.append(k, String(v))
    try { const r = await apiUpload<{ title: string }>('/grab/upload', form); msg = `Added ${r.title}` } catch (e: any) { msg = e.message }
  }
  async function addMagnet() {
    if (!magnet.trim()) return
    try {
      await api('/grab', 'POST', { title: magnet.trim().slice(0, 80), download_url: magnet.trim(), ...grabBody })
      msg = 'Magnet added'; magnet = ''
    } catch (e: any) { msg = e.message }
  }
  const gb = (n: number) => (n / 1e9).toFixed(2) + ' GB'
  const shown = $derived(
    releases
      .filter((r) => showRejected || r.accepted)
      .toSorted((a, b) => sort === 'seeders' ? b.seeders - a.seeders : sort === 'size' ? a.size - b.size
        : Number(b.accepted) - Number(a.accepted) || b.score - a.score),
  )
  const rejectedCount = $derived(releases.filter((r) => !r.accepted).length)
</script>

<div class="modal">
  <div class="box">
    <button class="close" onclick={onclose}>✕</button>
    <h3>Releases</h3>
    {#if loading}<p>Searching indexers…</p>{/if}
    {#each errors as e}<p class="err">{e.indexer}: {e.error}</p>{/each}
    {#if msg}<p>{msg}</p>{/if}
    <div class="own">
      <label class="pick">Upload a .torrent you found yourself<input type="file" accept=".torrent" onchange={(e) => uploadFile(e.currentTarget.files)} hidden /></label>
      <form onsubmit={(e) => { e.preventDefault(); addMagnet() }}><input placeholder="…or paste a magnet link" bind:value={magnet} /><button>Add</button></form>
    </div>
    <div class="bar">
      <label><input type="checkbox" bind:checked={showRejected} /> Show rejected ({rejectedCount})</label>
      <label>Sort <select bind:value={sort}><option value="score">Best match</option><option value="seeders">Seeders</option><option value="size">Size</option></select></label>
      <span>{shown.length} shown</span>
    </div>
    <table>
      <tbody>
        {#each shown as r}
          <tr class:rej={!r.accepted}>
            <td>{r.title}<br /><small>{r.indexer} · {r.resolution ? r.resolution + 'p ' : ''}{r.source ?? ''} {r.codec ?? ''}{r.hdr ? ' HDR' : ''} · score {r.score}
              {#if !r.accepted}· {r.reasons.join(', ')}{/if}</small></td>
            <td>{gb(r.size)}</td><td>{r.seeders}↑</td>
            <td><button onclick={() => grab(r)}>Grab</button></td>
          </tr>
        {/each}
      </tbody>
    </table>
    {#if !loading && releases.length === 0}<p>No releases found.</p>{:else if !loading && shown.length === 0}<p>All {releases.length} releases were rejected by the quality profile – tick “Show rejected” to see why.</p>{/if}
  </div>
</div>

<style>
  .modal { position: fixed; inset: 0; background: #000a; display: flex; align-items: center; justify-content: center; }
  .box { background: #1c2128; padding: 1rem; border-radius: 8px; width: min(1000px, 95vw); max-height: 85vh; overflow: auto; position: relative; }
  .close { position: absolute; right: .5rem; top: .5rem; }
  table { width: 100%; border-collapse: collapse; }
  td { padding: .4rem; border-bottom: 1px solid #2b3340; font-size: .85rem; }
  .rej { opacity: .55; }
  .own { display: flex; gap: 1rem; align-items: center; flex-wrap: wrap; margin: .3rem 0; font-size: .85rem; }
  .pick { color: #6ea0ff; cursor: pointer; text-decoration: underline; } .own form { display: flex; gap: .3rem; flex: 1; } .own input { flex: 1; padding: .3rem; }
  .bar { display: flex; gap: 1.2rem; align-items: center; margin: .4rem 0; font-size: .85rem; }
  .err { color: #f66; }
</style>
