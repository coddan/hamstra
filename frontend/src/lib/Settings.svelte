<script lang="ts">
  import { api, type MovieRules } from './api'
  import Users from './Users.svelte'
  import Profiles from './Profiles.svelte'
  import MusicProfile from './MusicProfile.svelte'
  import Indexers from './Indexers.svelte'
  import MediaFolders from './MediaFolders.svelte'
  import { auth } from './auth.svelte'

  let rules = $state<MovieRules | null>(null)
  let certs = $state('')
  let genres = $state('')
  let msg = $state('')
  let tab = $state(auth.user && !auth.user.is_admin ? 'users' : 'quality')
  const tabs = [['quality', 'Quality profiles'], ['music', 'Music quality'], ['subtitles', 'Subtitles'], ['indexers', 'Indexers'], ['downloads', 'Downloads & seeding'], ['connections', 'Plex & notifications'], ['library', 'Library'], ['users', 'Users']]

  const split = (s: string) => s.split(',').map((x) => x.trim()).filter(Boolean)

  $effect(() => {
    api<MovieRules>('/settings/movie-rules').then((r) => {
      rules = r; certs = r.kids_certifications.join(', '); genres = r.kids_genres.join(', ')
    })
  })

  async function save() {
    if (!rules) return
    rules = await api<MovieRules>('/settings/movie-rules', 'PUT', {
      ...rules, kids_certifications: split(certs), kids_genres: split(genres),
    })
    msg = 'Saved'
  }
  type Section = Record<string, any>
  let engine = $state<Section>({})
  let plex = $state<Section>({})
  let notif = $state<Section>({})
  let seed = $state<Section>({})
  let dl = $state<Section>({})
  let auto = $state<Section>({})
  let sub = $state<Section>({})
  let trakt = $state<Section>({})
  let listUrl = $state('')
  let listSearch = $state(false)
  $effect(() => {
    api<Section>('/settings/engine').then((r) => (engine = r))
    api<Section>('/settings/plex').then((r) => (plex = r))
    api<Section>('/settings/notifications').then((r) => (notif = r))
    api<Section>('/settings/seeding').then((r) => (seed = r))
    api<Section>('/settings/downloads').then((r) => (dl = r))
    api<Section>('/settings/automation').then((r) => (auto = r))
    api<Section>('/settings/subtitles').then((r) => (sub = r))
    api<Section>('/settings/trakt').then((r) => (trakt = r))
  })
  async function saveSection(name: string, data: Section) {
    await api(`/settings/${name}`, 'PUT', data)
    msg = `Saved ${name}`
  }
  let plexInfo = $state<{ title: string; type: string; folders: string[] }[] | null>(null)
  async function testPlex() {
    const r = await api<{ ok: boolean; error?: string; sections?: { title: string; type: string; folders: string[] }[] }>('/settings/plex/test', 'POST')
    plexInfo = r.ok ? r.sections ?? [] : null
    msg = r.ok ? 'Plex connected' : `Plex: ${r.error}`
  }
  async function testSubs() {
    await saveSection('subtitles', sub)
    const r = await api<{ ok: boolean; error?: string }>('/settings/subtitles/test', 'POST')
    msg = r.ok ? 'OpenSubtitles login works' : `OpenSubtitles: ${r.error}`
  }
  async function runSubs() {
    msg = 'Looking for subtitles…'
    try { const r = await api<any>('/commands/subtitles', 'POST'); msg = r.error ?? `Downloaded ${r.downloaded}, not found ${r.not_found}${r.stopped ? ' – ' + r.stopped : ''}` } catch (e: any) { msg = e.message }
  }
  async function importList() {
    msg = 'Importing list…'
    try {
      const r = await api<{ added: string[]; skipped: string[]; failed: { item: string; reason: string }[] }>('/library/import-list', 'POST', { list: listUrl, search_now: listSearch })
      msg = `Added ${r.added.length}, already had ${r.skipped.length}, failed ${r.failed.length}${r.failed.length ? ' (' + r.failed.map((f) => f.item + ': ' + f.reason).join('; ') + ')' : ''}`
    } catch (e: any) { msg = e.message }
  }
  async function importAll() {
    type Job = { running: boolean; total: number; done: number; result: unknown }
    let job = await api<Job>('/library/import', 'POST')
    while (job.running) {
      msg = `Importing… ${job.done}/${job.total}`
      await new Promise((r) => setTimeout(r, 2000))
      job = await api<Job>('/library/import')
    }
    const r = job.result as any
    msg = r?.error ? `Error: ${r.error}` : `Added ${r?.added?.length ?? 0}, could not match ${r?.failed?.length ?? 0}`
  }
  async function scan() {
    msg = JSON.stringify(await api('/library/scan', 'POST'))
  }
</script>

<div class="tabbar">
  {#each tabs.filter(([id]) => !auth.user || auth.user.is_admin || id === 'users') as [id, label]}<button class:on={tab === id} onclick={() => (tab = id)}>{label}</button>{/each}
</div>
{#if msg}<p class="msg">{msg}</p>{/if}

{#if tab === 'quality'}
  <p>Profiles decide which releases are accepted and which one is picked. Each movie or series uses one profile; new items get the default (★).</p>
  <Profiles />
{/if}

{#if tab === 'music'}<MusicProfile />{/if}
{#if tab === 'subtitles'}
  <h3>Subtitles (OpenSubtitles.com)</h3>
  <p><small>Downloads subtitles for movies and episodes that are on disk and don't have one yet, saved next to the video (e.g. <code>Movie (2010).sv.srt</code>),
    so Plex picks them up. You need your own free account and API key at opensubtitles.com. The free plan only allows a few downloads per day;
    the app stops cleanly when the quota is used up and continues tomorrow.</small></p>
  <label class="inline"><input type="checkbox" bind:checked={sub.enabled} /> Download subtitles automatically (twice a day)</label>
  <label>API key <input type="password" bind:value={sub.api_key} autocomplete="off" /></label>
  <label>Username <input bind:value={sub.username} autocomplete="off" /></label>
  <label>Password <input type="password" bind:value={sub.password} autocomplete="off" /></label>
  <label>Languages (codes, comma separated) <input bind:value={sub.languages} placeholder="sv,en" /></label>
  <label>Max downloads per run <input type="number" min="1" bind:value={sub.limit_per_run} /></label>
  <button onclick={() => saveSection('subtitles', sub)}>Save</button>
  <button onclick={testSubs}>Save &amp; test login</button>
  <button onclick={runSubs}>Run now</button>
{/if}
{#if tab === 'indexers'}<p>Where releases are searched. Lower priority numbers are searched and preferred first; switch one off to skip it.</p><Indexers />{/if}

{#if tab === 'library'}
<MediaFolders />
<h3>Movie routing (kids vs adults)</h3>
{#if rules}
  <label>Kids certifications <input bind:value={certs} /></label>
  <label>Kids genres (used when no certification) <input bind:value={genres} /></label>
  <label><input type="checkbox" bind:checked={rules.use_genres_when_no_certification} /> Use genres when no certification</label>
  <label>Default when undecided
    <select bind:value={rules.default_kind}>
      <option value="movies_adults">adults</option><option value="movies_kids">kids</option>
    </select>
  </label>
  <button onclick={save}>Save</button>
{/if}
<h3>Library</h3>
<button onclick={scan}>Scan media folders</button>
<button onclick={importAll}>Auto-match unmatched folders</button>
<p><small>Folders that can't be matched automatically are listed under <b>Unmatched</b> in the menu, where you can pick the title yourself.</small></p>
<h3>Import a list (TMDB or Trakt)</h3>
<p><small>Adds every movie and series on a public list that isn't in the library yet. Paste a themoviedb.org list link or id, or a trakt.tv list or chart link
  (e.g. <code>trakt.tv/movies/trending</code>). Trakt needs your own client id, from trakt.tv/oauth/applications.</small></p>
<label>List URL or ID <input bind:value={listUrl} placeholder="https://www.themoviedb.org/list/8123456  or  https://trakt.tv/users/name/lists/list" /></label>
<label>Trakt client id (only for Trakt links) <input type="password" bind:value={trakt.client_id} autocomplete="off" /></label>
<button onclick={() => saveSection('trakt', trakt)}>Save Trakt id</button>
<label><input type="checkbox" bind:checked={listSearch} /> Search for them right away</label>
<button onclick={importList} disabled={!listUrl}>Import list</button>
{/if}

{#if tab === 'downloads'}
<h3>Torrent client</h3>
<label>Engine
  <select bind:value={engine.type}><option value="libtorrent">Built-in (libtorrent)</option><option value="qbittorrent">qBittorrent</option></select>
</label>
{#if engine.type === 'qbittorrent'}
  <label>URL <input bind:value={engine.url} placeholder="http://qbittorrent:8080" /></label>
  <label>Username <input bind:value={engine.username} /></label>
  <label>Password <input type="password" bind:value={engine.password} /></label>
{:else}
  <label>Bind to network interface (VPN) <input bind:value={engine.bind_interface} placeholder="tun0 / wg0 (optional)" /></label>
{/if}
{#if engine.type === 'qbittorrent'}
  <label>VPN interface to watch (kill switch) <input bind:value={engine.bind_interface} placeholder="tun0 / wg0 (optional)" /></label>
{/if}
<p><small>With a VPN interface set, nothing is grabbed and active torrents are paused while it is down.</small></p>
<button onclick={() => saveSection('engine', engine)}>Save</button>

<h3>Automatic downloading</h3>
<p><small>When on, the app looks for new releases every 15 minutes and searches for missing items every hour, then downloads them by itself.
  <b>Dry run</b> only records what it <i>would</i> download (see History on the Queue page) – use it for a day first.</small></p>
<label class="inline"><input type="checkbox" bind:checked={auto.enabled} /> Automatic downloading enabled</label>
<label class="inline"><input type="checkbox" bind:checked={auto.dry_run} /> Dry run (do not actually download)</label>
<label class="inline"><input type="checkbox" bind:checked={auto.rss} /> Watch new releases (every 15 min)</label>
<label class="inline"><input type="checkbox" bind:checked={auto.search} /> Search for missing items (hourly)</label>
<button onclick={() => saveSection('automation', auto)}>Save</button>

<h3>Download safety</h3>
<label>Give up on a download with no progress for (hours, 0 = never) <input type="number" min="0" step="1" bind:value={dl.stall_hours} /></label>
<label>Do not start downloads when free space is below (GB, 0 = no check) <input type="number" min="0" step="5" bind:value={dl.min_free_gb} /></label>
<button onclick={() => saveSection('downloads', dl)}>Save</button>

<h3>Seeding</h3>
<p>Finished downloads are copied into the library, kept seeding, then removed from the download folder when the rule is met.</p>
<label>Minimum ratio <input type="number" step="0.1" bind:value={seed.ratio} /></label>
<label>Minimum seeding hours <input type="number" step="1" bind:value={seed.hours} /></label>
<label>Remove when
  <select bind:value={seed.mode}><option value="either">ratio OR time reached</option><option value="both">ratio AND time reached</option></select>
</label>
<button onclick={() => saveSection('seeding', seed)}>Save</button>

{/if}

{#if tab === 'connections'}
<h3>Plex</h3>
<label>URL <input bind:value={plex.url} placeholder="http://plex:32400" /></label>
<label>Token <input type="password" bind:value={plex.token} /></label>
<button onclick={() => saveSection('plex', plex)}>Save</button>
<button onclick={testPlex}>Test connection</button>
{#if plexInfo}<ul>{#each plexInfo as s}<li>{s.title} ({s.type}) – {s.folders.join(', ')}</li>{/each}</ul>{/if}

<h3>Notifications</h3>
<label>Webhook URL (Discord/Slack compatible) <input type="password" bind:value={notif.webhook_url} /></label>
<button onclick={() => saveSection('notifications', notif)}>Save</button>

{/if}

{#if tab === 'users'}<Users />{/if}

<style>
  .tabbar { display: flex; gap: .4rem; flex-wrap: wrap; margin-bottom: 1rem; }
  .tabbar .on { background: #3b6fd8; color: #fff; }
  .msg { background: #1c2128; padding: .4rem .7rem; border-radius: 6px; }
  label { display: block; margin: .5rem 0; } label.inline { display: flex; gap: .4rem; align-items: center; }
  input:not([type='checkbox']) { width: 24rem; max-width: 100%; padding: .3rem; display: block; }
</style>
