export function bytes(n: number | null | undefined): string {
  if (n == null) return '–'
  const u = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  let v = n
  while (v >= 1000 && i < u.length - 1) { v /= 1000; i++ }
  return `${v >= 100 || i === 0 ? v.toFixed(0) : v.toFixed(1)} ${u[i]}`
}

export const speed = (n: number | null | undefined) => (n ? `${bytes(n)}/s` : '0 B/s')

export function duration(seconds: number | null | undefined): string {
  if (seconds == null) return '–'
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (d) return `${d}d ${h}h`
  if (h) return `${h}h ${m}m`
  return `${m}m`
}
