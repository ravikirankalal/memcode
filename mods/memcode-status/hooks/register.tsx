import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Feed, FeedEvent } from '../types'

// memcode rewrites <repo>/.memcode/activity.json whenever it saves or injects memory (memcode/activity.py).
const feed = atom({ plugin: 'memcode-status', key: 'feed' } as const, null)
const hint = atom({ plugin: 'memcode-status', key: 'hint' } as const, null)
const now = atom({ plugin: 'memcode-status', key: 'now' } as const, 0)
const since = atom({ plugin: 'memcode-status', key: 'since' } as const, 0) // this session's start (ms)

const POLL_MS = 2000
const FRESH_MS = 10 * 60 * 1000 // the latest event is shown this long, then only the counts
const FRESH_BOLD_MS = 15 * 1000 // an event this new is drawn bold
const SAVED_HOLD_MS = 90 * 1000 // a new memory stays the headline this long even if other events follow
const BUSY_STALE_MS = 5 * 60 * 1000 // a busy mark older than this was left by a worker that died

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
  touch: { icon: '📂', tag: 'FOLDER', color: 'planMode' }, // a folder's memories on its first read
  held: { icon: '✋', tag: 'HELD', color: 'warning' },
  start: { icon: '🚀', tag: 'LOADED', color: 'claude' },
  scanned: { icon: '🔍', tag: 'SCANNED', color: 'ide' }, // the memory agent read the latest turns
}
const OTHER: Look = { icon: '•', tag: 'EVENT', color: 'inactive' }

// standing problems (memcode/activity.py `problems`), most serious first; each holds the bar until memcode clears it
const PROBLEMS: [string, Look][] = [
  ['capture', { icon: '⚠', tag: 'PROBLEM', color: 'error' }], // #34: the memory agent's model calls fail
  ['budget', { icon: '💸', tag: 'BUDGET', color: 'warning' }], // this session's scan budget is spent
]

// what this session's tally counts, in display order
const TALLY: [string, string][] = [['saved', 'saved'], ['updated', 'updated'], ['retired', 'retired']]
// injections: memories memcode put into the coding agent's context (an event's n is how many), in display order
const INJECTIONS: [string, string][] = [['start', 'at start'], ['recalled', 'recalled'], ['touch', 'on first touch'],
  ['held', 'on held writes']]

export function problemOf(f: Feed): { look: Look; text: string } | null {
  const ps = f.problems ?? {}
  for (const [k, lk] of PROBLEMS) if (ps[k]) return { look: lk, text: ps[k] }
  const other = Object.values(ps)[0]
  return other ? { look: PROBLEMS[0][1], text: other } : null
}

export function look(kind: string): Look {
  return LOOK[kind] ?? OTHER
}

export function parseFeed(text: string): Feed | null {
  try {
    const d = JSON.parse(text)
    if (!d || typeof d !== 'object' || !d.counts || !Array.isArray(d.events)) return null
    const problems: Record<string, string> = {}
    if (d.problems && typeof d.problems === 'object') {
      for (const [k, v] of Object.entries(d.problems)) if (typeof v === 'string' && v) problems[k] = v
    }
    const busy: Record<string, number> = {}
    if (d.busy && typeof d.busy === 'object') {
      for (const [k, v] of Object.entries(d.busy)) if (typeof v === 'number' && v > 0) busy[k] = v
    }
    const counts = { memories: Number(d.counts.memories) || 0, from_you: Number(d.counts.from_you ?? d.counts.rules) || 0 }
    return { updated: Number(d.updated) || 0, counts, events: d.events, problems, busy }
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

function short(ms: number): string {
  return ago(ms).replace(' ago', '')
}

// the headline: a new memory holds the bar for a while; otherwise the latest event, except the agent's routine scans
// (a scan that kept something already shows as SAVED; one that kept nothing is shown as the agent's state instead)
export function latest(f: Feed, nowMs: number): FeedEvent | null {
  const saved = [...f.events].reverse().find(ev => ev.kind === 'saved' || ev.kind === 'updated' || ev.kind === 'retired')
  if (saved && nowMs - saved.ts * 1000 < SAVED_HOLD_MS) return saved
  const e = [...f.events].reverse().find(ev => ev.kind !== 'scanned')
  return e && nowMs - e.ts * 1000 < FRESH_MS ? e : null
}

// the memory agent right now: reading (busy mark), or when it last read a turn
export function agentState(f: Feed, nowMs: number): { reading: boolean; lastScan: FeedEvent | null } {
  const mark = f.busy?.agent
  const reading = !!mark && nowMs - mark * 1000 < BUSY_STALE_MS
  const lastScan = [...f.events].reverse().find(ev => ev.kind === 'scanned') ?? null
  return { reading, lastScan }
}

// what memcode did in this session (events since the session started), e.g. "3 saved · 2 recalled"
export function tally(f: Feed, sinceMs: number): string {
  const n: Record<string, number> = {}
  for (const ev of f.events) if (ev.ts * 1000 >= sinceMs) n[ev.kind] = (n[ev.kind] ?? 0) + 1
  return TALLY.filter(([k]) => n[k]).map(([k, label]) => `${n[k]} ${label}`).join(' · ')
}

// memories injected into the coding agent's context this session: the total and where they went in
export function injected(f: Feed, sinceMs: number): { total: number; detail: string } {
  const n: Record<string, number> = {}
  for (const ev of f.events) {
    if (ev.ts * 1000 >= sinceMs && INJECTIONS.some(([k]) => k === ev.kind)) n[ev.kind] = (n[ev.kind] ?? 0) + (Number(ev.n) || 0)
  }
  const total = Object.values(n).reduce((a, b) => a + b, 0)
  return { total, detail: INJECTIONS.filter(([k]) => n[k]).map(([k, label]) => `${n[k]} ${label}`).join(', ') }
}

// terminal columns a string takes (wide emoji count twice; variation selectors take none)
export function cols(s: string): number {
  let w = 0
  for (const ch of s) {
    if (ch === '️') continue
    w += /\p{Extended_Pictographic}/u.test(ch) ? 2 : 1
  }
  return w
}

function clip(s: string, width: number): string {
  if (cols(s) <= width) return s
  let out = ''
  for (const ch of s) {
    if (cols(out + ch) > width - 1) break
    out += ch
  }
  return `${out}…`
}

// what fits: the counts and the headline always show; this session's tally, then the agent's state, then the count
// labels give way on a narrow terminal so the headline keeps room
export function layout(width: number, parts: { counts: string; countsShort: string; head: number; agent: string; tally: string }):
  { long: boolean; agent: boolean; tally: boolean; head: number } {
  const brand = cols('◆ memcode ')
  const sep = 5 // "  ┃ " and spacing
  const minHead = parts.head ? Math.min(parts.head, 40) : 0
  let long = true
  let withAgent = !!parts.agent
  let withTally = !!parts.tally
  const used = () => brand + cols(long ? parts.counts : parts.countsShort) + (parts.head ? sep : 0) +
    (withAgent ? cols(parts.agent) + 2 : 0) + (withTally ? cols(parts.tally) + 2 : 0)
  if (withTally && width - used() < minHead) withTally = false
  if (withAgent && width - used() < minHead) withAgent = false
  if (width - used() < minHead) long = false
  return { long, agent: withAgent, tally: withTally, head: Math.max(12, width - used()) }
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
  const reading = !!f && agentState(f, t).reading
  // relative ages move on even when nothing new happened; while the agent reads, every poll (the dots move)
  if (changed || reading || t - lastTick > 15000) {
    lastUpdated = f?.updated ?? 0
    lastTick = t
    await update($, now, () => t)
    if (changed) await update($, feed, () => f)
  }
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const result = await next(e)
    const t = await $.clock.now()
    await update($, since, () => t)
    // a worktree session: hooks may keep the store in the main working tree (#32), so look in both roots
    const roots = [await $.session.root(), (await $.session.repo().catch(() => null))?.root]
    paths = [...new Set(roots.filter((r): r is string => !!r))].map(r => `${r}/.memcode/activity.json`)
    path = paths[0] ?? ''
    await refresh($).catch(() => undefined)
    $.clock.every(POLL_MS, () => void refresh($).catch(() => undefined))
    // last, and on its own: a host without commands still gets the bar
    await $.command
      .register({ name: 'memcode-status', description: 'memcode: what it holds, what the memory agent is doing, recent activity' })
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
    if (!f) {
      const why = (await read($, hint)) || 'memcode has not written anything in this repository yet'
      return { text: `◆ memcode: ${why}\n  feed: ${path || '(no repository root)'}` }
    }
    const c = f.counts
    const lines = [`◆ memcode: ${c.memories} memories, ${c.from_you} from you`]
    for (const [k, lk] of PROBLEMS) if (f.problems[k]) lines.push(`  ${lk.icon} ${lk.tag}: ${f.problems[k]}`)
    const st = agentState(f, t)
    lines.push(st.reading ? '  🔍 memory agent: reading the latest turn now'
      : st.lastScan ? `  🔍 memory agent: last read ${ago(t - st.lastScan.ts * 1000)} (${st.lastScan.text})`
        : '  🔍 memory agent: has not read a turn yet')
    const s0 = (await read($, since)) || 0
    const tl = tally(f, s0)
    const inj = injected(f, s0)
    const parts = [inj.total ? `${inj.total} injected (${inj.detail})` : '', tl].filter(Boolean)
    lines.push(`  this session: ${parts.join(' · ') || 'nothing injected or saved yet'}`)
    const recent = f.events.slice(-8).reverse()
    if (recent.length) {
      lines.push('', 'recent:')
      const pad = Math.max(...recent.map(ev => look(ev.kind).tag.length))
      for (const ev of recent) {
        const lk = look(ev.kind)
        lines.push(`  ${lk.icon} ${lk.tag.padEnd(pad)}  ${ev.text}  (${ago(t - ev.ts * 1000)})`)
      }
    }
    if (!Object.keys(renders).length) {
      const surfaces = await $.session.surfaces()
      lines.push('', surfaces.length
        ? `status bar: not drawn yet (surfaces: ${surfaces.join(', ')})`
        : 'status bar: this session has no terminal or desktop surface, so the bar cannot be drawn here')
    }
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
    const { Box, Text } = $.ui.resolve(e)
    const c = f.counts
    const problem = problemOf(f)
    const ev = problem ? null : latest(f, t)
    const lk = ev ? look(ev.kind) : null
    const fresh = !!ev && t - ev.ts * 1000 < FRESH_BOLD_MS
    const st = agentState(f, t)
    const dots = '.'.repeat(1 + (Math.floor(t / POLL_MS) % 3))
    const agentText = st.reading ? `🔍 reading${dots}` : st.lastScan ? `🔍 ${short(t - st.lastScan.ts * 1000)}` : ''
    const s0 = (await read($, since)) || 0
    const tl = tally(f, s0)
    const inj = injected(f, s0).total
    const tallyText = [inj ? `📥${inj} injected` : '', tl ? `+${tl}` : ''].filter(Boolean).join('  ')
    const headText = problem ? problem.text : ev ? ev.text : ''
    const headLook = problem ? problem.look : lk
    const headCols = headText ? cols(` ${headLook!.icon} ${headLook!.tag} `) + 1 + cols(headText) + (ev ? 10 : 0) : 0
    const fit = layout(e.props.bodyColumns || 120, {
      counts: `${c.memories} memories · ${c.from_you} from you`,
      countsShort: `🧠${c.memories} 📜${c.from_you}`,
      head: headCols, agent: agentText, tally: tallyText,
    })
    const badgeCols = headLook ? cols(` ${headLook.icon} ${headLook.tag} `) + 1 : 0
    const text = clip(headText, Math.max(8, fit.head - badgeCols - (ev ? 10 : 0)))

    return (
      <Box flexDirection="row">
        <Text color="claude" bold>◆ memcode </Text>
        {fit.long ? (
          <Text>
            <Text color="remember" bold>{c.memories}</Text>
            <Text dimColor> memories · </Text>
            <Text color="merged" bold>{c.from_you}</Text>
            <Text dimColor> from you</Text>
          </Text>
        ) : (
          <Text>
            <Text color="remember">🧠{c.memories} </Text>
            <Text color="merged">📜{c.from_you}</Text>
          </Text>
        )}
        {headLook && (
          <Text>
            <Text dimColor>  ┃ </Text>
            <Text backgroundColor={headLook.color} color="inverseText" bold> {headLook.icon} {headLook.tag} </Text>
            <Text color={headLook.color} bold={problem ? false : fresh}> {text}</Text>
            {ev && <Text dimColor> · {ago(t - ev.ts * 1000)}</Text>}
          </Text>
        )}
        {fit.agent && <Text color={st.reading ? 'ide' : undefined} dimColor={!st.reading}>  {agentText}</Text>}
        {fit.tally && <Text color="success" dimColor>  {tallyText}</Text>}
      </Box>
    )
  })
}
