import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Feed, FeedEvent } from '../types'

// memcode rewrites <repo>/.memcode/activity.json whenever it saves or injects memory (memcode/activity.py).
const feed = atom({ plugin: 'memcode-status', key: 'feed' } as const, null)
const now = atom({ plugin: 'memcode-status', key: 'now' } as const, 0)

const POLL_MS = 2000
const FRESH_MS = 10 * 60 * 1000 // the latest event is shown this long, then only the counts

const LABEL: Record<string, { icon: string; color: string }> = {
  saved: { icon: '+', color: 'success' },
  recalled: { icon: '↻', color: 'suggestion' },
  touch: { icon: '→', color: 'suggestion' },
  held: { icon: '⏸', color: 'warning' },
  start: { icon: '•', color: 'subtle' },
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

export function latest(f: Feed, nowMs: number): FeedEvent | null {
  const e = f.events[f.events.length - 1]
  return e && nowMs - e.ts * 1000 < FRESH_MS ? e : null
}

// module state: a reload starts it over, which only costs one extra read
let path = ''
let lastUpdated = -1
let lastTick = 0
const renders: Record<string, number> = {} // surface -> times the band was asked for (shown by /memcode-status)

async function refresh($: EngineInterface): Promise<void> {
  if (!path) return
  const t = await $.clock.now()
  let f: Feed | null = null
  try {
    f = parseFeed(await $.fs.read(path))
  } catch {
    f = null // no store yet: memcode is not active in this repo
  }
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
    path = `${await $.session.root()}/.memcode/activity.json`
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
      `surfaces in this session: ${surfaces.join(', ') || 'none'}`,
      `status bar asked for by: ${drawn}`,
    ]
    return { text: lines.join('\n') }
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    renders[e.surface] = (renders[e.surface] ?? 0) + 1
    const f = await read($, feed)
    if (e.props.hasSurvey || f === null) return next(e)
    const t = (await read($, now)) || (await $.clock.now())
    const ev = latest(f, t)
    const { Box, Text } = $.ui.resolve(e)
    const c = f.counts
    const label = ev ? LABEL[ev.kind] ?? { icon: '·', color: 'subtle' } : null
    const width = Math.max(20, e.props.bodyColumns - 46)
    const text = ev && ev.text.length > width ? `${ev.text.slice(0, width - 1)}…` : ev?.text

    return (
      <Box flexDirection="row">
        <Text color="claude" bold>memcode</Text>
        <Text dimColor> {c.memories} memories · {c.rules} rules · {c.facts} facts</Text>
        {ev && label && (
          <Text>
            <Text dimColor>  │ </Text>
            <Text color={label.color}>{label.icon} {text}</Text>
            <Text dimColor> {ago(t - ev.ts * 1000)}</Text>
          </Text>
        )}
      </Box>
    )
  })
}
