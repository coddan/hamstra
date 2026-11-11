import { auth } from './auth.svelte'

export async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const headers: Record<string, string> = {}
  if (body) headers['content-type'] = 'application/json'
  const res = await fetch(`/api/v1${path}`, { method, headers, body: body ? JSON.stringify(body) : undefined })
  if (res.status === 401) {
    auth.needsLogin = true
    throw new Error('Please sign in')
  }
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}))
    throw new Error(detail.detail ?? `${res.status} ${res.statusText}`)
  }
  return res.status === 204 ? (undefined as T) : res.json()
}

export type Movie = {
  id: number; tmdb_id: number; title: string; year: number | null; poster_url: string | null
  certification: string | null; has_file: boolean; root_kind: string | null; overview: string | null
  monitored: boolean; absolute_numbering?: boolean
}
export type Series = {
  id: number; tvmaze_id: number; title: string; year: number | null; poster_url: string | null
  status: string | null; episode_count: number; file_count: number; overview: string | null
  monitored: boolean
}
export type MovieRules = {
  kids_certifications: string[]; kids_genres: string[]
  use_genres_when_no_certification: boolean; default_kind: string
}
export type Release = {
  title: string; indexer: string; size: number; seeders: number; download_url: string
  info_hash: string | null; accepted: boolean; reasons: string[]; score: number
  resolution: number | null; source: string | null; codec: string | null; hdr?: boolean
}

export async function apiUpload<T>(path: string, form: FormData): Promise<T> {
  const res = await fetch(`/api/v1${path}`, { method: 'POST', body: form })
  if (res.status === 401) {
    auth.needsLogin = true
    throw new Error('Please sign in')
  }
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}))
    throw new Error(detail.detail ?? `${res.status} ${res.statusText}`)
  }
  return res.json()
}
