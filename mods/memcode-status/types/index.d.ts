export type FeedEvent = { ts: number; kind: string; text: string; n: number }
export type Feed = {
  updated: number
  counts: { memories: number; rules: number; notes: number; facts: number }
  events: FeedEvent[]
}

declare module 'claude-code' {
  interface PluginState {
    'memcode-status': { feed: Feed | null; now: number }
  }
}
