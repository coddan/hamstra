const PAGES = ['dashboard', 'movies', 'series', 'monitoring', 'music', 'others', 'queue', 'system', 'settings', 'requests']

// The current page lives in the URL hash (#/settings/indexers) so a refresh or a bookmark opens the same place.
function parseHash(): { page: string; sub: string } {
  const [page, sub] = location.hash.replace(/^#\/?/, '').split('/')
  return { page: PAGES.includes(page) ? page : 'dashboard', sub: sub ?? '' }
}

const start = parseHash()

export const nav = $state({
  page: start.page,
  openMovie: null as number | null,   // open the interactive search for this movie id
  showMovie: null as number | null,   // open the detail window of this movie id
  openSeries: null as number | null,  // open the detail page of this series id
  othersTab: (start.page === 'others' && start.sub === 'unmatched' ? 'unmatched' : 'dl') as 'dl' | 'unmatched',  // which tab Others should show
  settingsTab: start.page === 'settings' ? start.sub : '',  // which tab Settings should show ('' = default)
})

export function hashFor(): string {
  const sub = nav.page === 'others' ? nav.othersTab : nav.page === 'settings' ? nav.settingsTab : ''
  return '#/' + nav.page + (sub ? '/' + sub : '')
}

export function syncFromHash(): void {
  const h = parseHash()
  nav.page = h.page
  if (h.page === 'others') nav.othersTab = h.sub === 'unmatched' ? 'unmatched' : 'dl'
  if (h.page === 'settings') nav.settingsTab = h.sub
}
