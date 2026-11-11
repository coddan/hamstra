<script lang="ts">
  import { api } from './api'

  let { onclose, onadded, onchoose }: { onclose: () => void; onadded: () => void; onchoose: (id: number) => void } = $props()
  type Alb = { mbid: string; title: string; artist: string; artist_mbid: string | null; year: number | null; kind: string | null
    cover_url: string | null; in_library: boolean; note?: string }
  type Art = { mbid: string; name: string; disambiguation: string; country: string; type: string }

  let q = $state('')
  let mode = $state<'album' | 'artist'>('album')
  let albums = $state<Alb[]>([])
  let artists = $state<Art[]>([])
  let artistName = $state('')
  let busy = $state(false)
  let msg = $state('')
  let folders = $state<string[]>([])
  let genre = $state('')          // '' = automatic
  let newGenre = $state('')
  let input: HTMLInputElement

  $effect(() => { input?.focus(); api<{ folders: string[] }>('/music/folders').then((r) => (folders = r.folders)).catch(() => {}) })

  async function search() {
    if (!q.trim()) return
    busy = true; msg = ''; artistName = ''
    try {
      if (mode === 'album') { albums = await api(`/music/search?q=${encodeURIComponent(q)}`); artists = [] }
      else { artists = await api(`/music/search?q=${encodeURIComponent(q)}&type=artist`); albums = [] }
    } catch (e: any) { msg = e.message }
    busy = false
  }
  async function showArtist(a: Art) {
    busy = true; msg = ''
    try { albums = await api(`/music/artists/${a.mbid}/albums`); artists = []; artistName = a.name } catch (e: any) { msg = e.message }
    busy = false
  }
  const chosenGenre = $derived(genre === '__new' ? newGenre.trim() : genre)

  async function add(a: Alb, how: 'choose' | 'auto' | 'only') {
    a.note = 'Adding…'
    try {
      const r = await api<any>('/music/albums', 'POST', {
        mbid: a.mbid, artist: a.artist, artist_mbid: a.artist_mbid, title: a.title, year: a.year, kind: a.kind, cover_url: a.cover_url,
        genre: chosenGenre, search_now: how === 'auto',
      })
      a.in_library = true
      onadded()
      if (how === 'choose' && !r.has_files) { onchoose(r.id); return }
      a.note = r.has_files ? 'Already in your music folder – linked' : how === 'auto' ? (r.grabbed ? `Grabbed: ${r.grabbed}` : r.search_error ?? 'Added – no suitable release found') : 'Added'
    } catch (e: any) { a.note = e.message }
  }
</script>

<div class="modal" role="presentation" onclick={(e) => e.target === e.currentTarget && onclose()}>
  <div class="box">
    <button class="close" onclick={onclose} aria-label="Close">✕</button>
    <h3>Add music</h3>
    <form onsubmit={(e) => { e.preventDefault(); search() }}>
      <select bind:value={mode}><option value="album">Album</option><option value="artist">Artist</option></select>
      <input bind:this={input} bind:value={q} placeholder={mode === 'album' ? 'e.g. pink floyd dark side of the moon' : 'Artist name'} />
      <button disabled={busy}>{busy ? 'Searching…' : 'Search'}</button>
    </form>
    <label class="dest">Put it in folder
      <select bind:value={genre}>
        <option value="">Automatic (next to the artist if known)</option>
        {#each folders as f}<option value={f}>{f}</option>{/each}
        <option value="__new">New folder…</option>
      </select>
      {#if genre === '__new'}<input placeholder="Folder name" bind:value={newGenre} />{/if}
    </label>
    {#if msg}<p class="err">{msg}</p>{/if}

    {#each artists as a}
      <div class="row"><div class="grow"><b>{a.name}</b> <small>{[a.type, a.country, a.disambiguation].filter(Boolean).join(' · ')}</small></div>
        <button onclick={() => showArtist(a)}>Show albums</button></div>
    {/each}
    {#if artistName}<h4>{artistName}</h4>{/if}
    {#each albums as a (a.mbid)}
      <div class="row">
        <img src={a.cover_url ?? ''} alt="" loading="lazy" onerror={(e) => ((e.currentTarget as HTMLElement).style.visibility = 'hidden')} />
        <div class="grow"><b>{a.title}</b> <small>{a.year ?? ''} · {a.kind ?? ''}</small><br /><small>{a.artist}</small>
          {#if a.note}<br /><em>{a.note}</em>{/if}</div>
        {#if a.in_library}<span class="have">In library</span>
        {:else}
          <div class="btns">
            <button class="choose" onclick={() => add(a, 'choose')}>🔍 Add &amp; choose release</button>
            <button onclick={() => add(a, 'auto')}>Add &amp; search automatically</button>
            <button class="alt" onclick={() => add(a, 'only')}>Add only</button>
          </div>
        {/if}
      </div>
    {/each}
  </div>
</div>

<style>
  .modal { position: fixed; inset: 0; background: #000a; display: flex; align-items: flex-start; justify-content: center; padding-top: 5vh; z-index: 20; }
  .box { background: #1c2128; padding: 1rem 1.2rem; border-radius: 10px; width: min(860px, 95vw); max-height: 88vh; overflow: auto; position: relative; }
  .close { position: absolute; right: .6rem; top: .6rem; background: none; border: 0; color: inherit; cursor: pointer; font-size: 1.1rem; }
  form { display: flex; gap: .5rem; margin-bottom: .6rem; } form input { flex: 1; padding: .45rem; } select { padding: .35rem; }
  .dest { display: flex; gap: .5rem; align-items: center; margin-bottom: .7rem; font-size: .85rem; flex-wrap: wrap; } .dest input { padding: .3rem; }
  .row { display: flex; gap: .8rem; align-items: center; padding: .45rem 0; border-bottom: 1px solid #2b3340; } .grow { flex: 1; }
  img { width: 56px; height: 56px; object-fit: cover; border-radius: 4px; background: #2b3340; flex: none; }
  .btns { display: flex; flex-direction: column; gap: .3rem; } .have { color: #3fb950; } em { color: #7fd48b; font-style: normal; }
  button { background: #3b6fd8; color: #fff; border: 0; border-radius: 5px; padding: .35rem .7rem; cursor: pointer; }
  button.alt { background: #2b3340; } button.choose { background: #1f7a4d; } .err { color: #f66; }
</style>
