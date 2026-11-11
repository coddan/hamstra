<script lang="ts">
  import { api } from './api'

  type U = { path: string; kind: 'movie' | 'tv'; name: string; title: string; year: number | null; root: string
    duplicate_of: string | null; guess: 'movie' | 'series' | 'collection'; videos: number | null; is_dir: boolean; mismatch: boolean }
  type G = { path: string; name: string; kind: string; score: number; title: string; year: number | null; poster_url: string | null }
  type R = { tmdb_id?: number; tvmaze_id?: number; title: string; year: number | null; poster_url: string | null; in_library?: boolean }

  let items = $state<U[]>([])
  let collections = $state<string[]>([])
  let ignoredCount = $state(0)
  let loading = $state(true)
  let tab = $state<'todo' | 'guess' | 'dups' | 'cols'>('todo')
  let guesses = $state<G[]>([])
  let filter = $state('')
  let limit = $state(30)
  let open = $state<string | null>(null)
  let as = $state<'movie' | 'series'>('movie')
  let query = $state('')
  let lang = $state('en-US')
  let results = $state<R[]>([])
  let busy = $state(false)
  let msg = $state('')
  let job = $state('')
  let note = $state('')

  async function load() {
    loading = true
    const r = await api<{ items: U[]; ignored: number; collections: string[] }>('/library/unmatched')
    items = r.items; ignoredCount = r.ignored; collections = r.collections; loading = false
    guesses = await api('/library/guessed')
  }
  $effect(() => { load() })

  const todo = $derived(items.filter((i) => !i.duplicate_of))
  const dups = $derived(items.filter((i) => i.duplicate_of))
  const shown = $derived(todo.filter((i) => !filter || i.name.toLowerCase().includes(filter.toLowerCase())))
  const guessLabel = { movie: '🎬 Looks like a movie', series: '📺 Looks like a series', collection: '🗂 Several different films' }
  const base = (p: string) => p.split('/').filter(Boolean).slice(-1)[0]

  async function openRow(u: U) {
    open = u.path; msg = ''; results = []
    as = u.guess === 'series' ? 'series' : 'movie'  // by name; change it with the switch if that is wrong
    query = u.title
    search()
    if (u.is_dir && u.videos === null) {           // look inside only when the row is opened (the share is slow)
      try {
        const i = await api<{ guess: U['guess']; videos: number }>(`/library/inspect?path=${encodeURIComponent(u.path)}`)
        u.videos = i.videos; u.guess = i.guess
        if (open === u.path && i.guess === 'series' && as !== 'series') { as = 'series'; search() }
      } catch { /* keep the cheap guess */ }
    }
  }
  async function search() {
    if (!query.trim()) return
    busy = true; msg = ''
    const u = items.find((i) => i.path === open)
    try {
      results = as === 'movie'
        ? await api(`/movies/lookup?q=${encodeURIComponent(query)}&lang=${lang}${u?.year ? `&year=${u.year}` : ''}`)
        : await api(`/series/lookup?q=${encodeURIComponent(query)}`)
      if (as === 'movie' && u?.year && results.length === 0) results = await api(`/movies/lookup?q=${encodeURIComponent(query)}&lang=${lang}`)
    } catch (e: any) { msg = e.message }
    busy = false
  }
  async function match(u: U, r: R) {
    try {
      const res = await api<{ title: string; episodes?: number; files_found?: number; has_file?: boolean }>('/library/match', 'POST',
        { path: u.path, kind: as === 'movie' ? 'movie' : 'tv', tmdb_id: r.tmdb_id, tvmaze_id: r.tvmaze_id })
      items = items.filter((i) => i.path !== u.path); open = null
      if (res.episodes !== undefined) {
        note = res.files_found
          ? `✓ Linked to “${res.title}”: ${res.files_found} of ${res.episodes} episodes found on disk.`
          : `Linked to “${res.title}”, but no episode files were recognised. The files need names like S01E02 (or 1x02) to be matched to episodes.`
      } else note = res.has_file ? `✓ Linked to “${res.title}”.` : `Linked to “${res.title}”, but no video file was found in that folder.`
    } catch (e: any) { msg = e.message }
  }
  async function ignore(u: U) {
    await api('/library/ignore', 'POST', { path: u.path })
    items = items.filter((i) => i.path !== u.path); ignoredCount++; open = null
  }
  async function splitFolder(u: U) {
    if (!confirm(`Split "${u.name}" into separate films?\n\nUse this only if the folder holds several DIFFERENT films. Each film file inside is then matched on its own. Nothing is moved or renamed.`)) return
    await api('/library/collection', 'POST', { path: u.path })
    job = 'Matching the files inside…'; await autoMatch()
  }
  async function undo(p: string) { await api('/library/uncollection', 'POST', { path: p }); await load() }
  async function ignoreDups() {
    if (!confirm(`Ignore ${dups.length} folders that are second copies of something already in the library?`)) return
    await api('/library/ignore-duplicates', 'POST'); await load()
  }
  async function confirmGuess(g: G) { await api('/library/guessed/confirm', 'POST', { path: g.path }); guesses = guesses.filter((x) => x.path !== g.path) }
  async function undoGuess(g: G) { await api('/library/guessed/undo', 'POST', { path: g.path }); await load() }
  async function confirmAll() {
    if (!confirm(`Mark all ${guesses.length} guesses as correct?`)) return
    await api('/library/guessed/confirm-all', 'POST'); guesses = []
  }
  async function bestGuess() {
    if (!confirm('Link every remaining folder to its closest match?\n\nWeak matches are listed under “Best guesses” so you can check them and undo any that are wrong. No files are touched.')) return
    await autoMatch(true); tab = 'guess'
  }
  async function autoMatch(guess = false) {
    type Job = { running: boolean; total: number; done: number; result: any }
    let j = await api<Job>(`/library/import${guess ? '?guess=true' : ''}`, 'POST')
    while (j.running) {
      job = `Matching… ${j.done}/${j.total}`
      await new Promise((r) => setTimeout(r, 2000))
      j = await api<Job>('/library/import')
    }
    job = `Done: linked ${j.result?.added?.length ?? 0}${j.result?.guessed ? ` (${j.result.guessed} by best guess)` : ''}${j.result?.collections?.length ? `, split ${j.result.collections.length} collection folder(s)` : ''}`
    await load()
  }
</script>

<p class="intro">The app links each folder in your media folders to a title (movie or series) so it knows what you have.
  Most are done automatically. <b>These are the ones it could not decide.</b> Linking never moves or renames files.</p>

<ul class="help">
  <li><b>Find match</b> – search for the title and pick the right one. This is what you want for almost everything, movies and series alike.</li>
  <li><b>Contains several films</b> – only for a folder that holds many different films (e.g. a box set). Each film file inside is then matched separately.</li>
  <li><b>Ignore</b> – hide the folder (extras, junk, things you don't want linked).</li>
</ul>
{#if note}<p class="note">{note}</p>{/if}

<div class="top">
  <button onclick={() => autoMatch(false)}>Run auto-match again</button>
  <button class="go" onclick={bestGuess} title="Also accept close matches; they are listed for review">Auto-match everything (best guess)</button><span>{job}</span>
</div>

<div class="tabs">
  <button class:on={tab === 'todo'} onclick={() => (tab = 'todo')}>Needs a decision ({todo.length})</button>
  <button class:on={tab === 'guess'} onclick={() => (tab = 'guess')}>Best guesses ({guesses.length})</button>
  <button class:on={tab === 'dups'} onclick={() => (tab = 'dups')}>Duplicates ({dups.length})</button>
  <button class:on={tab === 'cols'} onclick={() => (tab = 'cols')}>Collection folders ({collections.length})</button>
  <span class="grow"></span><small>{ignoredCount} ignored</small>
</div>
{#if loading}<p>Scanning folders…</p>{/if}

{#if tab === 'todo'}
  <input class="filter" placeholder="Filter…" bind:value={filter} />
  {#each shown.slice(0, limit) as u (u.path)}
    <div class="row">
      <div class="line">
        {#if u.mismatch}<span class="chip warn" title="The name looks like a series, but this folder is set up for movies">⚠ Looks like a series, in a movies folder</span>
        {:else}<span class="chip {u.guess}">{guessLabel[u.guess]}</span>{/if}
        <span class="name" title={u.path}>{u.name}<br /><small>in {base(u.root)}{u.videos && u.videos > 1 ? ` · ${u.videos} video files` : ''}</small></span>
        <button class="go" onclick={() => (open === u.path ? (open = null) : openRow(u))}>{open === u.path ? 'Close' : 'Find match'}</button>
        {#if u.is_dir && u.guess !== 'series'}
          <button class:go={u.guess === 'collection'} onclick={() => splitFolder(u)} title="Only if this folder holds several different films">Contains several films</button>
        {/if}
        <button class="dim" onclick={() => ignore(u)}>Ignore</button>
      </div>
      {#if open === u.path}
        <div class="panel">
          <div class="seg">This is a
            <button class:on={as === 'movie'} onclick={() => { as = 'movie'; search() }}>Movie</button>
            <button class:on={as === 'series'} onclick={() => { as = 'series'; search() }}>Series</button>
          </div>
          <form onsubmit={(e) => { e.preventDefault(); search() }}>
            <input bind:value={query} />
            {#if as === 'movie'}<select bind:value={lang} onchange={search}><option value="en-US">English titles</option><option value="sv-SE">Swedish titles</option></select>{/if}
            <button disabled={busy}>{busy ? 'Searching…' : 'Search'}</button>
          </form>
          {#if u.guess === 'collection'}<p class="hint">This folder holds several different films – use <b>Contains several films</b> above instead of picking one title.</p>
          {:else if as === 'series'}<p class="hint">Pick the show this folder belongs to. Episodes are linked from file names like S01E02. Swedish shows are often listed under another title: try the English title, or paste an IMDb link or id (tt…).</p>
          {:else}<p class="hint">Pick the film this is. Try the Swedish-titles option if the folder has a Swedish name.</p>{/if}
          {#if msg}<p class="err">{msg}</p>{/if}
          {#each results as r}
            <div class="res">
              {#if r.poster_url}<img src={r.poster_url} alt="" loading="lazy" />{:else}<div class="noimg"></div>{/if}
              <span class="grow"><b>{r.title}</b> {r.year ?? ''}{r.in_library ? ' · already in library' : ''}</span>
              <button class="go" onclick={() => match(u, r)}>This one</button>
            </div>
          {/each}
          {#if !busy && results.length === 0}<p><small>No results. Try another spelling or the original title, paste an IMDb link, or switch between Movie and Series above. If you can't find it, press Ignore.</small></p>{/if}
        </div>
      {/if}
    </div>
  {/each}
  {#if shown.length > limit}<button onclick={() => (limit += 50)}>Show more ({shown.length - limit} left)</button>{/if}
  {#if !loading && todo.length === 0}<p>Nothing left to decide. 🎉</p>{/if}
{/if}

{#if tab === 'guess'}
  <p><small>These folders were linked to the <i>closest</i> match, not an exact one. Check them (lowest confidence first). <b>Looks right</b> keeps it, <b>Wrong</b> unlinks it again and puts the folder back under “Needs a decision”. No files are touched either way.</small></p>
  {#if guesses.length}<button onclick={confirmAll}>Mark all as correct</button>{/if}
  {#each guesses as g (g.path)}
    <div class="row"><div class="line">
      {#if g.poster_url}<img src={g.poster_url} alt="" loading="lazy" />{:else}<div class="noimg"></div>{/if}
      <span class="name"><small>{g.name}</small><br />→ <b>{g.title}</b> {g.year ?? ''} <span class="chip {g.kind === 'series' ? 'series' : 'movie'}">{g.kind === 'series' ? 'Series' : 'Movie'}</span>
        <span class="conf" class:low={g.score < 0.8}>{Math.round(Math.min(g.score, 1) * 100)}% sure</span></span>
      <button class="go" onclick={() => confirmGuess(g)}>Looks right</button>
      <button class="dim" onclick={() => undoGuess(g)}>Wrong</button></div></div>
  {:else}<p>No best guesses to review.</p>{/each}
{/if}

{#if tab === 'dups'}
  <p><small>The same film or show already exists in the library, stored in another folder. Nothing to do unless you want to clean up the extra copy yourself.</small></p>
  {#if dups.length}<button onclick={ignoreDups}>Ignore all {dups.length}</button>{/if}
  {#each dups as u (u.path)}
    <div class="row"><div class="line"><span class="name">{u.name}<br /><small class="dup">same as {base(u.duplicate_of ?? '')}</small></span>
      <button class="dim" onclick={() => ignore(u)}>Ignore</button></div></div>
  {/each}
{/if}

{#if tab === 'cols'}
  <p><small>Folders that hold several different films. Each file inside is linked on its own.</small></p>
  {#each collections as c}
    <div class="row"><div class="line"><span class="name" title={c}>{base(c)}</span><button class="dim" onclick={() => undo(c)}>Undo</button></div></div>
  {:else}<p>None.</p>{/each}
{/if}

<style>
  .intro { max-width: 46rem; } .help { max-width: 52rem; margin: .4rem 0 .8rem; padding-left: 1.1rem; font-size: .9rem; opacity: .9; } .help li { margin: .2rem 0; }
  .note { background: #1d3a2a; padding: .5rem .8rem; border-radius: 6px; } .hint { font-size: .85rem; opacity: .8; margin: .3rem 0; } .top { display: flex; gap: .8rem; align-items: center; margin-bottom: .6rem; }
  .tabs { display: flex; gap: .4rem; align-items: center; margin: .6rem 0; flex-wrap: wrap; } .tabs .on, .seg .on { background: #3b6fd8; color: #fff; }
  .filter { padding: .4rem; width: 20rem; margin-bottom: .6rem; } .grow { flex: 1; }
  .row { background: #1c2128; border-radius: 6px; padding: .45rem .7rem; margin-bottom: .3rem; }
  .line { display: flex; gap: .6rem; align-items: center; } .name { flex: 1; word-break: break-all; font-size: .9rem; }
  .chip { font-size: .72rem; padding: .1rem .5rem; border-radius: 999px; white-space: nowrap; background: #2d4a7a; }
  .chip.series { background: #6a3d7a; } .chip.warn { background: #7a5a2d; } .conf { font-size: .75rem; color: #3fb950; margin-left: .4rem; } .conf.low { color: #c9a227; } .chip.collection { background: #7a5a2d; }
  .panel { margin-top: .5rem; border-top: 1px solid #2b3340; padding-top: .5rem; } .seg { display: flex; gap: .4rem; align-items: center; margin-bottom: .4rem; }
  form { display: flex; gap: .4rem; margin: .4rem 0; } form input { flex: 1; padding: .35rem; }
  .res { display: flex; gap: .6rem; align-items: center; padding: .25rem 0; border-top: 1px solid #2b3340; }
  img, .noimg { width: 36px; height: 54px; object-fit: cover; background: #2b3340; border-radius: 3px; }
  button { background: #2b3340; color: inherit; border: 0; border-radius: 4px; padding: .3rem .7rem; cursor: pointer; } button.go { background: #3b6fd8; color: #fff; } .dim { opacity: .75; }
  .err { color: #f66; } .dup { color: #c9a227; }
</style>
