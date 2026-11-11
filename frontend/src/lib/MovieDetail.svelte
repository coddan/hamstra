<script lang="ts">
  import { api, type Movie } from './api'

  let { id, onclose, onchanged, onsearch }: { id: number; onclose: () => void; onchanged: () => void; onsearch: (m: Movie) => void } = $props()
  type M = Movie & { quality_profile_id: number | null; root_folder_id: number | null; release_date: string | null; imdb_id: string | null; path: string | null }
  type Root = { id: number; path: string; kind: string }

  let m = $state<M | null>(null)
  let profiles = $state<{ id: number; name: string }[]>([])
  let roots = $state<Root[]>([])
  let msg = $state('')

  async function load() { m = (await api<M[]>('/movies')).find((x) => x.id === id) ?? null }
  $effect(() => {
    load()
    api<typeof profiles>('/profiles').then((p) => (profiles = p))
    api<Root[]>('/system/rootfolders').then((r) => (roots = r.filter((x) => x.kind.startsWith('movies')))).catch(() => {})
  })

  async function patch(body: Record<string, unknown>) {
    try { await api(`/movies/${id}`, 'PATCH', body); msg = 'Saved'; await load(); onchanged() } catch (e: any) { msg = e.message; await load() }
  }
  async function auto() {
    msg = 'Searching…'
    try { const r = await api<{ grabbed: string | null }>(`/movies/${id}/search`, 'POST'); msg = r.grabbed ? `Grabbed ${r.grabbed}` : 'No suitable release found' } catch (e: any) { msg = e.message }
  }
  async function remove() {
    if (!m || !confirm(`Remove "${m.title}" from the library?`)) return
    const files = m.has_file && confirm('Also DELETE its files from disk?\n\nOK = delete the files too\nCancel = keep the files, only remove it from the library')
    try { await api(`/movies/${id}?delete_files=${files}`, 'DELETE'); onchanged(); onclose() } catch (e: any) { msg = e.message }
  }
  const label = (r: Root) => r.path.split('/').filter(Boolean).slice(-1)[0] + (r.kind === 'movies_kids' ? ' (kids)' : ' (adults)')
</script>

<div class="modal" role="presentation" onclick={(e) => e.target === e.currentTarget && onclose()}>
  <div class="box">
    <button class="close" onclick={onclose} aria-label="Close">✕</button>
    {#if m}
      <div class="head">
        {#if m.poster_url}<img src={m.poster_url} alt="" />{:else}<div class="noimg"></div>{/if}
        <div>
          <h2>{m.title} <small>{m.year ?? ''}</small></h2>
          <p class="meta">{m.certification ? `Rated ${m.certification} · ` : ''}{m.release_date ? `Released ${m.release_date} · ` : ''}{m.has_file ? '✓ on disk' : '✗ not on disk'}</p>
          <p class="over">{m.overview ?? ''}</p>
        </div>
      </div>

      <div class="btns">
        <button class="go" onclick={() => { onclose(); onsearch(m!) }}>🔍 Interactive search</button>
        <button onclick={auto}>Search automatically</button>
      </div>

      <div class="grid">
        <label>Quality profile
          <select value={m.quality_profile_id ?? ''} onchange={(e) => e.currentTarget.value && patch({ quality_profile_id: Number(e.currentTarget.value) })}>
            {#if m.quality_profile_id === null}<option value="">Default profile</option>{/if}
            {#each profiles as p}<option value={p.id}>{p.name}</option>{/each}
          </select>
        </label>
        <label>Destination folder
          <select value={m.root_folder_id} disabled={m.has_file} onchange={(e) => patch({ root_folder_id: Number(e.currentTarget.value) })}>
            {#each roots as r}<option value={r.id}>{label(r)}</option>{/each}
          </select>
          {#if m.has_file}<small>Already on disk, so it can't be moved from here.</small>{/if}
        </label>
        <label class="inline"><input type="checkbox" checked={m.monitored} onchange={(e) => patch({ monitored: e.currentTarget.checked })} /> Monitored (search for it automatically)</label>
      </div>
      <p class="path"><small>{m.path ?? ''}</small></p>
      <button class="danger" onclick={remove}>Remove from library…</button>
    {:else}<p>Loading…</p>{/if}
    {#if msg}<p class="msg">{msg}</p>{/if}
  </div>
</div>

<style>
  .modal { position: fixed; inset: 0; background: #000a; display: flex; align-items: flex-start; justify-content: center; padding-top: 6vh; z-index: 20; }
  .box { background: #1c2128; padding: 1rem 1.2rem; border-radius: 10px; width: min(720px, 95vw); max-height: 86vh; overflow: auto; position: relative; }
  .close { position: absolute; right: .6rem; top: .6rem; background: none; border: 0; color: inherit; cursor: pointer; font-size: 1.1rem; }
  .head { display: flex; gap: 1rem; } img, .noimg { width: 120px; aspect-ratio: 2/3; object-fit: cover; background: #2b3340; border-radius: 6px; flex: none; }
  h2 { margin: 0 0 .3rem; } .meta { opacity: .8; margin: .2rem 0; } .over { font-size: .9rem; opacity: .9; }
  .btns { display: flex; gap: .5rem; margin: .8rem 0; } .grid { display: grid; gap: .7rem; }
  label { display: flex; flex-direction: column; gap: .2rem; } label.inline { flex-direction: row; align-items: center; gap: .4rem; } select { padding: .35rem; }
  button { background: #2b3340; color: inherit; border: 0; border-radius: 5px; padding: .4rem .9rem; cursor: pointer; } button.go { background: #3b6fd8; color: #fff; }
  .path { word-break: break-all; opacity: .7; } .danger { background: #3a2226; color: #f99; } .msg { background: #14171c; padding: .4rem .7rem; border-radius: 6px; }
</style>
