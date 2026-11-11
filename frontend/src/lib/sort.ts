const ARTICLE = /^(the|a|an)\s+/

export function sortKey(title: string): string {
  const t = title.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim()
  return t.replace(ARTICLE, '').replace(/^[^a-z0-9]+/, '')
}

export function letterOf(title: string): string {
  const c = sortKey(title).charAt(0).toUpperCase()
  return c >= 'A' && c <= 'Z' ? c : '#'
}

export const LETTERS = ['#', ...'ABCDEFGHIJKLMNOPQRSTUVWXYZ']
