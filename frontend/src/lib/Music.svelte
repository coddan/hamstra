<script lang="ts">
  import { api } from './api'
  import { auth } from './auth.svelte'
  import AddAlbum from './AddAlbum.svelte'
  import AZRail from './AZRail.svelte'
  import Releases from './Releases.svelte'
  import { letterOf, sortKey } from './sort'

  type Album = { id: number; mbid: string; artist: string; title: string; year: number | null; kind: string | null; cover_url: string | null
    monitored: boolean; has_files: boolean; file_format: string | null; genre: string; path: string | null }
  let albums = $state<Album[]>([])
  let loading = $state(true)
  let filter = $state('')
  let status = $state('all')
  let adding = $state(false)
  let releasesFor = $state<Album | null>(null)
  let detail = $state<Album | null>(null)
  let folders = $state<string[]>([])
  let msg = $state('')
  let active = $state('')
  let linking = $state(false)
  let linkGenre = $state('')
  let linkRetry = $state(false)
  let linkMsg = $state('')

  async function linkExisting() {
    type Job = { running: boolean; total: number; done: number; linked: number; result: any }
    let j = await api<Job>('/music/import', 'POST', { genre: linkGenre || null, retry: linkRetry })
    while (j.running) {
      linkMsg = `Looking up ${j.done}/${j.total} folders… linked ${j.linked}`
      await new Promise((r) => setTimeout(r, 3000))
      j = await api<Job>('/music/import')
    }
    linkMsg = j.result?.error ? `Error: ${j.result.error}` : `Done: linked ${j.result?.linked ?? 0}, not found ${j.result?.not_found ?? 0}`
    await load()
  }
  const admin = $derived(!auth.user || auth.user.is_admin)

  async function load() {
    loading = true
    albums = await api('/music/albums')
    loading = false
  }
  $effect(() => { load(); api<{ folders: string[] }>('/music/folders').then((r) => (folders = r.folders)).catch(() => {}) })

  const filtered = $derived.by(() => {
    const f = filter.trim().toLowerCase()
    return albums
      .filter((a) => !f || `${a.artist} ${a.title}`.toLowerCase().includes(f))
      .filter((a) => status === 'all' || (status === 'disk' ? a.has_files : !a.has_files))
      .sort((a, b) => sortKey(a.artist).localeCompare(sortKey(b.artist)) || (a.year ?? 0) - (b.year ?? 0))
  })
  const sections = $derived.by(() => {
    const m = new Map<string, Album[]>()
    for (const a of filtered) { const l = letterOf(a.artist); m.set(l, [...(m.get(l) ?? []), a]) }
    return [...m.entries()].sort(([a], [b]) => (a === '#' ? -1 : b === '#' ? 1 : a.localeCompare(b)))
  })
  const available = $derived(new Set(sections.map(([l]) => l)))
  const jump = (l: string) => document.getElementById(`mus-${l === '#' ? 'num' : l}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  function onscroll() {
    let cur = ''
    for (const [l] of sections) { const el = document.getElementById(`mus-${l === '#' ? 'num' : l}`); if (el && el.getBoundingClientRect().top <= 90) cur = l }
    active = cur
  }

  async function auto(a: Album) {
    msg = 'Searching…'
    try { const r = await api<{ grabbed: string | null }>(`/music/albums/${a.id}/search`, 'POST'); msg = r.grabbed ? `Grabbed ${r.grabbed}` : 'No suitable release found' } catch (e: any) { msg = e.message }
  }
  async function remove(a: Album) {
    if (!confirm(`Remove "${a.artist} – ${a.title}" from the library?`)) return
    const files = a.has_files && confirm('Also DELETE its files from disk?\n\nOK = delete files too\nCancel = keep the files')
    await api(`/music/albums/${a.id}?delete_files=${files}`, 'DELETE')
    detail = null; await load()
  }
  async function setGenre(a: Album, genre: string) {
    try { detail = await api<Album>(`/music/albums/${a.id}`, 'PATCH', { genre }); await load() } catch (e: any) { msg = e.message }
  }
  async function rescan(a: Album) { detail = await api<Album>(`/music/albums/${a.id}/rescan`, 'POST'); await load() }
  async function setMonitored(a: Album, v: boolean) { detail = await api<Album>(`/music/albums/${a.id}`, 'PATCH', { monitored: v }); await load() }
  async function choose(id: number) {
    adding = false; await load(); releasesFor = albums.find((x) => x.id === id) ?? null
  }
</script>

<svelte:window {onscroll} />

<div class="toolbar">
  <input class="search" bind:value={filter} placeholder="Filter artists and albums…" />
  <select bind:value={status}><option value="all">All</option><option value="disk">On disk</option><option value="missing">Missing</option></select>
  <span class="count">{filtered.length}{filtered.length !== albums.length ? ` / ${albums.length}` : ''}</span>
  {#if admin}<button class="alt" onclick={() => (linking = !linking)}>Link my existing music</button>
  <button class="add" onclick={() => (adding = true)}>+ Add music</button>{/if}
</div>
{#if linking}
  <div class="link">
    <p><small>Looks through your music folders and links each album you already have to its MusicBrainz entry, so this page shows what you own and nothing is downloaded twice.
      It needs about one lookup per second, so thousands of folders take a while; you can leave this page and it keeps going. Only albums whose artist and title both appear in the folder name are linked.</small></p>
    <select bind:value={linkGenre}><option value="">All folders</option>{#each folders as f}<option value={f}>{f}</option>{/each}</select>
    <label class="inline"><input type="checkbox" bind:checked={linkRetry} /> also retry folders that did not match before</label>
    <button class="primary" onclick={linkExisting}>Start</button> <span>{linkMsg}</span>
  </div>
{/if}
{#if msg}<p class="msg">{msg}</p>{/if}
{#if loading}<p>Loading…</p>
{:else if albums.length === 0}
  <p>No albums yet. Press <b>+ Add music</b> to search MusicBrainz, pick an album and choose the folder (e.g. a genre folder) it should go into.
    Albums you already have in the music folder are recognised when you add them.</p>
{/if}

<div class="body">
  {#each sections as [letter, list] (letter)}
    <section id={`mus-${letter === '#' ? 'num' : letter}`}>
      <h2>{letter}</h2>
      <div class="grid">
        {#each list as a (a.id)}
          <div class="card">
            <button class="cover" onclick={() => (detail = a)}>
              <img src={a.cover_url ?? ''} alt="" loading="lazy" onerror={(e) => ((e.currentTarget as HTMLElement).style.opacity = '0.15')} />
            </button>
            <div class="meta">
              <strong>{a.title}</strong> <span>{a.year ?? ''}</span>
              <small>{a.artist}</small>
              <em class:ok={a.has_files}>{a.has_files ? `on disk${a.file_format ? ' · ' + a.file_format : ''}` : 'missing'}</em>
              {#if admin && !a.has_files}<button class="primary" onclick={() => (releasesFor = a)}>🔍 Interactive search</button>
                <button onclick={() => auto(a)}>Search (auto)</button>{/if}
              {#if admin}<button class="danger" onclick={() => remove(a)}>Remove</button>{/if}
            </div>
          </div>
        {/each}
      </div>
    </section>
  {/each}
</div>
<AZRail {available} {active} onjump={jump} />

{#if adding}<AddAlbum onclose={() => (adding = false)} onadded={load} onchoose={choose} />{/if}
{#if releasesFor}
  <Releases path={`/music/albums/${releasesFor.id}/releases`} grabBody={{ album_id: releasesFor.id }} onclose={() => (releasesFor = null)} />
{/if}

{#if detail}
  {@const d = detail}
  <div class="modal" role="presentation" onclick={(e) => e.target === e.currentTarget && (detail = null)}>
    <div class="box">
      <button class="close" onclick={() => (detail = null)} aria-label="Close">✕</button>
      <div class="head">
        <img src={d.cover_url ?? ''} alt="" onerror={(e) => ((e.currentTarget as HTMLElement).style.opacity = '0.15')} />
        <div><h2>{d.title} <small>{d.year ?? ''}</small></h2><p>{d.artist} · {d.kind ?? 'Album'}</p>
          <p class="st">{d.has_files ? `✓ on disk${d.file_format ? ' (' + d.file_format + ')' : ''}` : '✗ not on disk'}</p></div>
      </div>
      {#if admin}
        <div class="btns2">
          {#if !d.has_files}<button class="primary" onclick={() => { releasesFor = d; detail = null }}>🔍 Interactive search</button>
            <button onclick={() => auto(d)}>Search automatically</button>{/if}
          <button onclick={() => rescan(d)}>Look for it in the music folder</button>
        </div>
        <label>Folder
          <select value={d.genre} disabled={d.has_files} onchange={(e) => setGenre(d, e.currentTarget.value)}>
            <option value="">(automatic / music root)</option>
            {#each folders as f}<option value={f}>{f}</option>{/each}
          </select>
        </label>
        <label class="inline"><input type="checkbox" checked={d.monitored} onchange={(e) => setMonitored(d, e.currentTarget.checked)} /> Monitored (search for it automatically)</label>
      {/if}
      <p class="path"><small>{d.path ?? `Will go into ${d.genre ? d.genre : 'the music folder'}, in a folder named like the release`}</small></p>
      {#if admin}<button class="danger" onclick={() => remove(d)}>Remove…</button>{/if}
    </div>
  </div>
{/if}

<style>
  .toolbar { position: sticky; top: 0; z-index: 4; display: flex; gap: .5rem; align-items: center; background: #14171ccc; backdrop-filter: blur(6px); padding: .6rem 0; margin-bottom: .5rem; }
  .search { flex: 1; max-width: 26rem; padding: .45rem .6rem; } select { padding: .4rem; } .count { opacity: .7; font-size: .85rem; }
  .alt { margin-left: auto; background: #2b3340; color: inherit; border: 0; border-radius: 6px; padding: .45rem .9rem; cursor: pointer; }
  .link { background: #1c2128; padding: .6rem .9rem; border-radius: 8px; margin-bottom: .8rem; display: flex; gap: .8rem; align-items: center; flex-wrap: wrap; } .link p { flex-basis: 100%; margin: 0; }
  .add { margin-left: 0; margin-right: 2.2rem; background: #3b6fd8; color: #fff; border: 0; border-radius: 6px; padding: .45rem .9rem; cursor: pointer; }
  .body { padding-right: 2.2rem; } section { scroll-margin-top: 4rem; content-visibility: auto; contain-intrinsic-size: 1px 400px; }
  h2 { margin: 1.2rem 0 .5rem; border-bottom: 1px solid #2b3340; padding-bottom: .2rem; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 1rem; } .card { background: #1c2128; border-radius: 8px; overflow: hidden; }
  .cover { padding: 0; border: 0; background: #2b3340; width: 100%; display: block; cursor: pointer; } .cover img { width: 100%; aspect-ratio: 1; object-fit: cover; display: block; }
  .meta { padding: .5rem; font-size: .85rem; display: flex; flex-direction: column; gap: .25rem; } span, small { opacity: .75; } em { font-style: normal; color: #c9a227; } em.ok { color: #3fb950; }
  button { background: #2b3340; color: inherit; border: 0; border-radius: 4px; padding: .25rem .5rem; cursor: pointer; } .primary { background: #3b6fd8; color: #fff; padding: .35rem .5rem; }
  .msg { background: #1c2128; padding: .4rem .7rem; border-radius: 6px; }
  .modal { position: fixed; inset: 0; background: #000a; display: flex; align-items: flex-start; justify-content: center; padding-top: 6vh; z-index: 20; }
  .box { background: #1c2128; padding: 1rem 1.2rem; border-radius: 10px; width: min(640px, 95vw); max-height: 86vh; overflow: auto; position: relative; }
  .close { position: absolute; right: .6rem; top: .6rem; background: none; font-size: 1.1rem; }
  .head { display: flex; gap: 1rem; } .head img { width: 140px; height: 140px; object-fit: cover; border-radius: 6px; background: #2b3340; } .head h2 { margin: 0 0 .3rem; border: 0; }
  .btns2 { display: flex; gap: .5rem; margin: .8rem 0; flex-wrap: wrap; } label { display: flex; flex-direction: column; gap: .2rem; margin: .5rem 0; } label.inline { flex-direction: row; align-items: center; gap: .4rem; }
  .path { word-break: break-all; opacity: .7; } .danger { background: #3a2226; color: #f99; align-self: flex-start; } .st { opacity: .9; }
</style>
