export type FeedEvent = { ts: number; kind: string; text: string; n: number }
export type Feed = {
  updated: number
  counts: { memories: number; from_you: number }
  events: FeedEvent[]
  problems: Record<string, string> // what is broken right now (memcode/activity.py), e.g. a failing memory agent
  busy: Record<string, number> // what is working right now: {agent: since (epoch s)} while the memory agent reads
}

declare module 'claude-code' {
  interface PluginState {
    'memcode-status': { feed: Feed | null; now: number; hint: string | null; since: number }
  }
}
