<script lang="ts">
  import { api, apiUpload } from './api'

  let { kind, onclose, onadded }: { kind: 'movies' | 'series'; onclose: () => void; onadded: () => void } = $props()
  type C = { tmdb_id?: number; tvmaze_id?: number; title: string; year: number | null; poster_url: string | null; in_library?: boolean }
  type Info = { name: string; kind: 'movie' | 'series' | null; title: string; year: number | null; season: number | null
    episodes: number[]; season_pack: boolean; candidates: C[]; note: string | null }

  let file = $state<File | null>(null)
  let magnet = $state('')
  let info = $state<Info | null>(null)
  let target = $state<'movie' | 'series'>(kind === 'movies' ? 'movie' : 'series')
  let cands = $state<C[]>([])
  let chosen = $state<C | null>(null)
  let season = $state<number | null>(null)
  let query = $state('')
  let over = $state(false)
  let busy = $state(false)
  let msg = $state('')
  let done = $state('')

  const idOf = (c: C) => (target === 'movie' ? c.tmdb_id : c.tvmaze_id)

  function form(extra: Record<string, string | number | null>): FormData {
    const f = new FormData()
    if (file) f.append('file', file); else f.append('magnet', magnet.trim())
    for (const [k, v] of Object.entries(extra)) if (v !== null && v !== undefined) f.append(k, String(v))
    return f
  }
  function pick(files: FileList | null) {
    if (files?.[0]) { file = files[0]; magnet = '' }
  }
  function drop(e: DragEvent) {
    e.preventDefault(); over = false
    pick(e.dataTransfer?.files ?? null)
  }

  async function inspect() {
    busy = true; msg = ''
    try {
      info = await apiUpload<Info>('/torrents/inspect', form({}))
      if (info.kind) target = info.kind
      cands = info.candidates
      chosen = cands.find((c) => c.in_library) ?? cands[0] ?? null
      season = info.season
      query = info.title
      if (info.note) msg = info.note
    } catch (e: any) { msg = e.message }
    busy = false
  }

  async function search() {
    busy = true; msg = ''
    try {
      const r = await api<C[]>(`/${target === 'movie' ? 'movies' : 'series'}/lookup?q=${encodeURIComponent(query)}`)
      cands = r; chosen = r[0] ?? null
    } catch (e: any) { msg = e.message }
    busy = false
  }

  async function submit() {
    if (!chosen) return
    busy = true; msg = ''
    try {
      const r = await apiUpload<{ title: string; library_item: string; season?: number; episodes?: number[] }>('/torrents/add', form({
        kind: target, tmdb_id: target === 'movie' ? chosen.tmdb_id! : null, tvmaze_id: target === 'series' ? chosen.tvmaze_id! : null,
        season: target === 'series' ? season : null,
      }))
      done = target === 'series'
        ? `Downloading for ${r.library_item}, season ${r.season}, episode${(r.episodes?.length ?? 0) > 1 ? 's' : ''} ${r.episodes?.join(', ')}. It is imported automatically when finished.`
        : `Downloading for ${r.library_item}. It is imported automatically when finished.`
      onadded()
    } catch (e: any) { msg = e.message }
    busy = false
  }
</script>

<div class="modal" role="presentation" onclick={(e) => e.target === e.currentTarget && onclose()}>
  <div class="box">
    <button class="close" onclick={onclose} aria-label="Close">✕</button>
    <h3>Add a torrent or magnet link</h3>

    {#if done}
      <p class="ok">{done}</p>
      <button onclick={onclose}>Close</button>
    {:else if !info}
      <p><small>For a release you found yourself. The app works out which {kind === 'movies' ? 'movie' : 'series'} it is, adds it to the library if needed,
        downloads it to the download folder and imports it like any other download.</small></p>
      <div class="drop" class:over role="presentation" ondragover={(e) => { e.preventDefault(); over = true }} ondragleave={() => (over = false)} ondrop={drop}>
        {#if file}<b>{file.name}</b> <button class="link" onclick={() => (file = null)}>remove</button>
        {:else}<b>Drop a .torrent file here</b> or
          <label class="pick">choose a file<input type="file" accept=".torrent" onchange={(e) => pick(e.currentTarget.files)} hidden /></label>{/if}
      </div>
      <input class="wide" placeholder="…or paste a magnet link" bind:value={magnet} disabled={!!file} />
      {#if msg}<p class="err">{msg}</p>{/if}
      <button class="primary" disabled={busy || (!file && !magnet.trim())} onclick={inspect}>{busy ? 'Reading…' : 'Next'}</button>
    {:else}
      <p class="rel"><small>Release:</small> {info.name || 'unnamed magnet link'}</p>
      <div class="seg">
        <button class:on={target === 'movie'} onclick={() => { target = 'movie'; if (query) search() }}>Movie</button>
        <button class:on={target === 'series'} onclick={() => { target = 'series'; if (query) search() }}>Series</button>
        {#if info.kind && info.kind !== target}<small>(detected: {info.kind})</small>{/if}
      </div>

      <form class="srch" onsubmit={(e) => { e.preventDefault(); search() }}>
        <input bind:value={query} placeholder="Search for the title…" /><button disabled={busy}>Search</button>
      </form>
      {#if msg}<p class="err">{msg}</p>{/if}
      <div class="list">
        {#each cands as c (idOf(c))}
          <label class="cand" class:sel={chosen && idOf(chosen) === idOf(c)}>
            <input type="radio" name="cand" checked={!!chosen && idOf(chosen) === idOf(c)} onchange={() => (chosen = c)} />
            {#if c.poster_url}<img src={c.poster_url} alt="" loading="lazy" />{:else}<div class="noimg"></div>{/if}
            <span><b>{c.title}</b> {c.year ?? ''}{c.in_library ? ' · in library' : ' · will be added'}</span>
          </label>
        {:else}<p><small>No suggestions – search for the title above.</small></p>{/each}
      </div>

      {#if target === 'series'}
        <label class="seas">Season
          <input type="number" min="0" bind:value={season} placeholder="?" />
          <small>{#if info.season_pack}season pack{:else if info.episodes.length}episode{info.episodes.length > 1 ? 's' : ''} {info.episodes.join(', ')} detected{:else}not detected – enter it{/if}</small>
        </label>
      {/if}
      <div class="btns">
        <button onclick={() => (info = null)}>Back</button>
        <button class="primary" disabled={busy || !chosen || (target === 'series' && season === null)} onclick={submit}>{busy ? 'Adding…' : 'Download'}</button>
      </div>
    {/if}
  </div>
</div>

<style>
  .modal { position: fixed; inset: 0; background: #000a; display: flex; align-items: flex-start; justify-content: center; padding-top: 6vh; z-index: 20; }
  .box { background: #1c2128; padding: 1rem 1.2rem; border-radius: 10px; width: min(640px, 95vw); max-height: 86vh; overflow: auto; position: relative; }
  .close { position: absolute; right: .6rem; top: .6rem; background: none; border: 0; color: inherit; cursor: pointer; font-size: 1.1rem; }
  .drop { border: 2px dashed #3a4556; border-radius: 10px; padding: 1.2rem; text-align: center; margin: .6rem 0; } .drop.over { border-color: #3b6fd8; background: #1d2a44; }
  .pick, .link { color: #6ea0ff; cursor: pointer; text-decoration: underline; background: none; border: 0; padding: 0; }
  .wide { width: 100%; padding: .5rem; box-sizing: border-box; margin-bottom: .6rem; }
  .rel { word-break: break-all; background: #14171c; padding: .4rem .6rem; border-radius: 6px; }
  .seg { display: flex; gap: .4rem; align-items: center; margin: .5rem 0; } .seg .on { background: #3b6fd8; color: #fff; }
  .srch { display: flex; gap: .4rem; } .srch input { flex: 1; padding: .4rem; }
  .list { margin: .6rem 0; max-height: 40vh; overflow: auto; }
  .cand { display: flex; gap: .6rem; align-items: center; padding: .3rem .4rem; border-radius: 6px; cursor: pointer; } .cand.sel { background: #26324a; }
  img, .noimg { width: 36px; height: 54px; object-fit: cover; background: #2b3340; border-radius: 3px; flex: none; }
  .seas { display: flex; gap: .6rem; align-items: center; margin: .5rem 0; } .seas input { width: 4rem; padding: .3rem; }
  .btns { display: flex; gap: .5rem; justify-content: flex-end; margin-top: .6rem; }
  button { background: #2b3340; color: inherit; border: 0; border-radius: 5px; padding: .4rem .9rem; cursor: pointer; }
  button.primary { background: #3b6fd8; color: #fff; } button:disabled { opacity: .5; cursor: default; }
  .err { color: #f66; } .ok { color: #7fd48b; }
</style>
