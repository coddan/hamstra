<script lang="ts">
  import { api } from './api'
  import { auth } from './auth.svelte'
  const canAdd = $derived(!auth.user || auth.user.is_admin)

  type Kind = 'movies' | 'series'
  let { kind, onclose, onadded, onchoose }: { kind: Kind; onclose: () => void; onadded: () => void; onchoose: (t: Kind, id: number) => void } = $props()
  type R = { type: Kind; tmdb_id?: number; tvmaze_id?: number; title: string; year: number | null; overview: string | null
    poster_url: string | null; in_library: boolean; note?: string }

  let q = $state('')
  let results = $state<R[]>([])
  let busy = $state(false)
  let searched = $state(false)
  let errors = $state<string[]>([])
  let input: HTMLInputElement
  let profiles = $state<{ id: number; name: string; is_default: boolean }[]>([])
  let profileId = $state<number | null>(null)
  type Root = { id: number; path: string; kind: string }
  let roots = $state<Root[]>([])
  let movieRoot = $state<number | null>(null)  // null = automatic (kids/adults rule)
  $effect(() => { if (canAdd) api<Root[]>('/system/rootfolders').then((r) => (roots = r)).catch(() => {}) })
  const movieRoots = $derived(roots.filter((r) => r.kind.startsWith('movies')))
  const label = (r: Root) => r.path.split('/').filter(Boolean).slice(-1)[0] + (r.kind === 'movies_kids' ? ' (kids)' : r.kind === 'movies_adults' ? ' (adults)' : '')
  $effect(() => { api<typeof profiles>('/profiles').then((p) => { profiles = p; profileId = p.find((x) => x.is_default)?.id ?? p[0]?.id ?? null }) })

  $effect(() => { input?.focus() })

  async function search() {
    if (!q.trim()) return
    busy = true; errors = []
    const order: Kind[] = kind === 'movies' ? ['movies', 'series'] : ['series', 'movies']
    const settled = await Promise.allSettled(order.map((t) => api<Omit<R, 'type'>[]>(`/${t}/lookup?q=${encodeURIComponent(q)}`)))
    results = settled.flatMap((r, i) => {
      if (r.status === 'rejected') { errors.push(`${order[i] === 'movies' ? 'Movies' : 'Series'}: ${r.reason.message}`); return [] }
      return r.value.map((x) => ({ ...x, type: order[i] }))
    })
    searched = true
    busy = false
  }

  async function request(r: R) {
    r.note = 'Requesting…'
    try {
      await api('/requests', 'POST', { kind: r.type === 'movies' ? 'movie' : 'series', external_id: r.type === 'movies' ? r.tmdb_id : r.tvmaze_id,
        title: r.title, year: r.year, poster_url: r.poster_url, overview: r.overview })
      r.note = 'Requested – an admin will review it'
    } catch (e: any) { r.note = e.message }
  }

  async function addAndChoose(r: R) {
    r.note = 'Adding…'
    try {
      const res = await api<{ id: number }>(`/${r.type}`, 'POST', {
        ...(r.type === 'movies' ? { tmdb_id: r.tmdb_id } : { tvmaze_id: r.tvmaze_id }), search_now: false, quality_profile_id: profileId,
        ...(r.type === 'movies' && movieRoot ? { root_folder_id: movieRoot } : {}),
      })
      r.in_library = true
      onchoose(r.type, res.id)
    } catch (e: any) { r.note = e.message }
  }

  async function add(r: R, searchNow: boolean) {
    r.note = searchNow ? 'Adding and searching indexers…' : 'Adding…'
    try {
      const res = await api<any>(`/${r.type}`, 'POST', {
        ...(r.type === 'movies' ? { tmdb_id: r.tmdb_id } : { tvmaze_id: r.tvmaze_id }), search_now: searchNow, quality_profile_id: profileId,
        ...(r.type === 'movies' && movieRoot ? { root_folder_id: movieRoot } : {}),
      })
      r.in_library = true
      r.note = res.search_error ? res.search_error
        : r.type === 'movies' ? (searchNow ? (res.grabbed ? `Grabbed: ${res.grabbed}` : 'Added – no suitable release found') : 'Added')
        : (searchNow ? `Added – grabbed ${res.search?.grabbed ?? 0} release(s), searched ${res.search?.searched ?? 0}` : 'Added')
      onadded()
    } catch (e: any) { r.note = e.message }
  }
</script>

<div class="modal" role="presentation" onclick={(e) => e.target === e.currentTarget && onclose()}>
  <div class="box">
    <button class="close" onclick={onclose} aria-label="Close">✕</button>
    <h3>{canAdd ? 'Add new movie or series' : 'Request a movie or series'}</h3>
    <form onsubmit={(e) => { e.preventDefault(); search() }}>
      <input bind:this={input} bind:value={q} placeholder="Search movies and series…" />
      <button disabled={busy}>{busy ? 'Searching…' : 'Search'}</button>
    </form>
    {#if canAdd && movieRoots.length > 0}
      <label class="prof">Movie destination
        <select bind:value={movieRoot}>
          <option value={null}>Automatic (kids or adults by rating)</option>
          {#each movieRoots as r}<option value={r.id}>{label(r)}</option>{/each}
        </select>
      </label>
    {/if}
    {#if canAdd && profiles.length > 1}
      <label class="prof">Quality profile <select bind:value={profileId}>{#each profiles as p}<option value={p.id}>{p.name}{p.is_default ? ' ★' : ''}</option>{/each}</select></label>
    {/if}
    {#each errors as e}<p class="err">{e}</p>{/each}
    <ul>
      {#each results as r}
        <li>
          {#if r.poster_url}<img src={r.poster_url} alt="" loading="lazy" />{:else}<div class="noimg"></div>{/if}
          <div class="info">
            <span class="ttl"><strong>{r.title}</strong> <span>{r.year ?? ''}</span> <b class="tag" class:tv={r.type === 'series'}>{r.type === 'series' ? 'Series' : 'Movie'}</b></span>
            <small>{r.overview?.slice(0, 200) ?? ''}</small>
            {#if r.note}<em>{r.note}</em>{/if}
          </div>
          {#if r.in_library}
            <span class="have">In library</span>
          {:else}
            <div class="btns">
              {#if canAdd}
                <button class="choose" onclick={() => addAndChoose(r)}>🔍 Add &amp; choose release</button>
                <button onclick={() => add(r, true)}>Add &amp; search automatically</button>
                <button class="alt" onclick={() => add(r, false)}>Add only</button>
              {:else}
                <button onclick={() => request(r)}>Request</button>
              {/if}
            </div>
          {/if}
        </li>
      {/each}
    </ul>
    {#if !busy && searched && results.length === 0 && errors.length === 0}<p>No results for “{q}”.</p>{/if}
  </div>
</div>

<style>
  .modal { position: fixed; inset: 0; background: #000a; display: flex; align-items: flex-start; justify-content: center; padding-top: 6vh; z-index: 20; }
  .box { background: #1c2128; padding: 1rem 1.2rem; border-radius: 10px; width: min(820px, 95vw); max-height: 85vh; overflow: auto; position: relative; }
  .close { position: absolute; right: .6rem; top: .6rem; background: none; border: 0; color: inherit; cursor: pointer; font-size: 1.1rem; }
  form { display: flex; gap: .5rem; margin-bottom: .8rem; }
  input { flex: 1; padding: .5rem; }
  ul { list-style: none; padding: 0; margin: 0; }
  li { display: flex; gap: .8rem; align-items: center; padding: .5rem 0; border-bottom: 1px solid #2b3340; }
  img, .noimg { width: 54px; height: 80px; object-fit: cover; border-radius: 4px; background: #2b3340; flex: none; }
  .info { flex: 1; display: flex; flex-direction: column; gap: .15rem; }
  span { opacity: .7; } small { opacity: .75; } em { color: #7fd48b; font-style: normal; }
  .btns { display: flex; flex-direction: column; gap: .3rem; }
  .have { color: #3fb950; white-space: nowrap; }
  button { background: #3b6fd8; color: #fff; border: 0; border-radius: 5px; padding: .35rem .7rem; cursor: pointer; }
  button.alt { background: #2b3340; } button.choose { background: #1f7a4d; }
  .err { color: #f66; }
  .prof { display: block; margin-bottom: .6rem; font-size: .85rem; } .prof select { margin-left: .4rem; padding: .25rem; }
  .tag { font-size: .7rem; padding: .05rem .4rem; border-radius: 4px; background: #2d4a7a; margin-left: .3rem; display: inline-block; align-self: flex-start; }
  .tag.tv { background: #6a3d7a; }
</style>
