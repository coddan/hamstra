export const nav = $state({
  page: 'dashboard',
  openMovie: null as number | null,   // open the interactive search for this movie id
  showMovie: null as number | null,   // open the detail window of this movie id
  openSeries: null as number | null,  // open the detail page of this series id
  othersTab: 'dl' as 'dl' | 'unmatched',  // which tab Others should show
})
