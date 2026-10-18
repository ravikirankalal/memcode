import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Feed, FeedEvent } from '../types'

// memcode rewrites <repo>/.memcode/activity.json whenever it saves or injects memory (memcode/activity.py).
const feed = atom({ plugin: 'memcode-status', key: 'feed' } as const, null)
const hint = atom({ plugin: 'memcode-status', key: 'hint' } as const, null)
const now = atom({ plugin: 'memcode-status', key: 'now' } as const, 0)

const POLL_MS = 2000
const FRESH_MS = 10 * 60 * 1000 // the latest event is shown this long, then only the counts

// each event kind: a badge (icon + word on a coloured background) and the colour of its text. Theme keys, so light and
// dark terminals both work; on a dark terminal: success green, warning yellow, suggestion light blue, planMode teal,
// merged lavender, claude salmon, inactive grey (checked in a real session)
type Look = { icon: string; tag: string; color: string }
const LOOK: Record<string, Look> = {
  saved: { icon: '🧠', tag: 'SAVED', color: 'success' },
  updated: { icon: '✏️', tag: 'UPDATED', color: 'success' },
  retired: { icon: '🗑', tag: 'RETIRED', color: 'inactive' },
  forgot: { icon: '🗑', tag: 'FORGOT', color: 'inactive' },
  recalled: { icon: '💡', tag: 'RECALLED', color: 'suggestion' },
  touch: { icon: '📂', tag: 'FOLDER RULES', color: 'planMode' },
  held: { icon: '✋', tag: 'HELD', color: 'warning' },
  start: { icon: '🚀', tag: 'LOADED', color: 'claude' },
}
const OTHER: Look = { icon: '•', tag: 'EVENT', color: 'inactive' }
const FRESH_BOLD_MS = 15 * 1000 // an event this new is drawn bold

export function look(kind: string): Look {
  return LOOK[kind] ?? OTHER
}

export function parseFeed(text: string): Feed | null {
  try {
    const d = JSON.parse(text)
    if (!d || typeof d !== 'object' || !d.counts || !Array.isArray(d.events)) return null
    return { updated: Number(d.updated) || 0, counts: d.counts, events: d.events }
  } catch {
    return null
  }
}

export function ago(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000))
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.round(s / 60)}m ago`
  return `${Math.round(s / 3600)}h ago`
}

const SAVED_HOLD_MS = 90 * 1000 // a new memory stays on the bar this long even if other events follow

export function latest(f: Feed, nowMs: number): FeedEvent | null {
  const saved = [...f.events].reverse().find(ev => ev.kind === 'saved' || ev.kind === 'updated' || ev.kind === 'retired')
  if (saved && nowMs - saved.ts * 1000 < SAVED_HOLD_MS) return saved
  const e = f.events[f.events.length - 1]
  return e && nowMs - e.ts * 1000 < FRESH_MS ? e : null
}

// module state: a reload starts it over, which only costs one extra read
let paths: string[] = [] // the session root's feed, then the repository root's (the main working tree in a worktree)
let path = '' // the feed shown: the newest of `paths`
let lastUpdated = -1
let lastTick = 0
const renders: Record<string, number> = {} // surface -> times the band was asked for (shown by /memcode-status)

async function refresh($: EngineInterface): Promise<void> {
  if (!paths.length) return
  const t = await $.clock.now()
  let f: Feed | null = null
  for (const p of paths) {
    let g: Feed | null = null
    try {
      g = parseFeed(await $.fs.read(p))
    } catch {
      g = null
    }
    if (g && (!f || g.updated > f.updated)) {
      f = g
      path = p
    }
  }
  // no feed: say why instead of hiding, when memcode's store is there (an older memcode writes no feed)
  let why: string | null = null
  if (f === null) {
    for (const p of paths) {
      if (await $.fs.exists(p.replace(/activity\.json$/, 'memory.db')).catch(() => false)) {
        why = 'memcode is active but writes no status feed: update memcode to 0.8.1 or later'
      }
    }
  }
  if (why !== (await read($, hint))) await update($, hint, () => why)
  const changed = (f?.updated ?? 0) !== lastUpdated
  if (changed || t - lastTick > 15000) {
    // relative ages move on even when nothing new happened
    lastUpdated = f?.updated ?? 0
    lastTick = t
    await update($, now, () => t)
    if (changed) await update($, feed, () => f)
  }
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const result = await next(e)
    // a worktree session: hooks may keep the store in the main working tree (#32), so look in both roots
    const roots = [await $.session.root(), (await $.session.repo().catch(() => null))?.root]
    paths = [...new Set(roots.filter((r): r is string => !!r))].map(r => `${r}/.memcode/activity.json`)
    path = paths[0] ?? ''
    await refresh($).catch(() => undefined)
    $.clock.every(POLL_MS, () => void refresh($).catch(() => undefined))
    // last, and on its own: a host without commands still gets the bar
    await $.command
      .register({ name: 'memcode-status', description: 'memcode: counts, recent memory events, where the status bar draws' })
      .catch(() => undefined)
    return result
  })

  on('prompt.submit', async ($, e, next) => {
    const result = await next(e)
    await refresh($).catch(() => undefined) // a status display never fails the call
    return result
  })

  on('tool.call', async ($, e, next) => {
    const result = await next(e)
    await refresh($).catch(() => undefined) // a status display never fails the call
    return result
  })

  on('command.run', { command: 'memcode-status' }, async $ => {
    await refresh($).catch(() => undefined)
    const f = await read($, feed)
    const t = await $.clock.now()
    const surfaces = await $.session.surfaces()
    const drawn = Object.entries(renders).map(([k, v]) => `${k} ${v}x`).join(', ') || 'not asked by any surface yet'
    const lines = [
      f ? `memcode: ${f.counts.memories} memories, ${f.counts.rules} rules, ${f.counts.facts} facts`
        : 'memcode: no activity feed in this repo yet (.memcode/activity.json)',
      ...(f ? f.events.slice(-5).map(ev => `  ${ev.kind}: ${ev.text} (${ago(t - ev.ts * 1000)})`) : []),
      `feed: ${path || '(not resolved yet)'}${f ? '' : ' (missing)'}`,
      ...(f ? [] : [`  ${(await read($, hint)) || 'no .memcode store here: memcode is not used in this repo'}`]),
      `surfaces in this session: ${surfaces.join(', ') || 'none'}`,
      `status bar asked for by: ${drawn}`,
    ]
    return { text: lines.join('\n') }
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    renders[e.surface] = (renders[e.surface] ?? 0) + 1
    const f = await read($, feed)
    if (e.props.hasSurvey) return next(e)
    if (f === null) {
      const why = await read($, hint)
      if (!why) return next(e) // memcode is not used in this repo: nothing of its own
      const { Text } = $.ui.resolve(e)
      return <Text dimColor>memcode · {why}</Text>
    }
    const t = (await read($, now)) || (await $.clock.now())
    const ev = latest(f, t)
    const { Box, Text } = $.ui.resolve(e)
    const c = f.counts
    const lk = ev ? look(ev.kind) : null
    const fresh = !!ev && t - ev.ts * 1000 < FRESH_BOLD_MS
    const width = Math.max(20, e.props.bodyColumns - 70)
    const text = ev && ev.text.length > width ? `${ev.text.slice(0, width - 1)}…` : ev?.text

    return (
      <Box flexDirection="row">
        <Text color="claude" bold>◆ memcode </Text>
        <Text color="merged">📜 {c.rules} </Text>
        <Text dimColor>rules  </Text>
        <Text color="suggestion">📝 {c.notes} </Text>
        <Text dimColor>notes  </Text>
        <Text color="planMode">⚙ {c.facts} </Text>
        <Text dimColor>facts</Text>
        {ev && lk && (
          <Text>
            <Text dimColor>  ┃ </Text>
            <Text backgroundColor={lk.color} color="inverseText" bold> {lk.icon} {lk.tag} </Text>
            <Text color={lk.color} bold={fresh}> {text}</Text>
            <Text dimColor> · {ago(t - ev.ts * 1000)}</Text>
          </Text>
        )}
      </Box>
    )
  })
}
