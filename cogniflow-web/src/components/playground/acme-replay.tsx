"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, ArrowRight, Clock, History, Loader2, MapPin } from "lucide-react";
import { api, type AuditBelief, type DemoSeed, type TimelineResponse } from "@/lib/api";

const cityOf = (statement: string) => {
  const m = statement.split(/\bin\b/i);
  return (m.length > 1 ? m[m.length - 1] : statement).replace(/[.\s]+$/, "").trim();
};
const ymd = (d: string | null) => (d ? d.slice(0, 10) : " - ");
const year = (iso: string) => iso.slice(0, 4);
const monthLabel = (iso: string) =>
  new Date(iso + "T00:00:00Z").toLocaleDateString("en-US", { month: "short", year: "numeric", timeZone: "UTC" });

export function AcmeReplay() {
  const [seed, setSeed] = useState<DemoSeed | null>(null);
  const [down, setDown] = useState(false);
  const [event2020, setEvent2020] = useState<AuditBelief[]>([]);
  const [bostonTl, setBostonTl] = useState<TimelineResponse | null>(null);
  const [denverTl, setDenverTl] = useState<TimelineResponse | null>(null);

  const [idx, setIdx] = useState(0);
  const [replay, setReplay] = useState<AuditBelief[]>([]);
  const [replayBusy, setReplayBusy] = useState(false);
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  // monthly ticks across the seeded system-time range
  const months = useMemo(() => {
    if (!seed) return [] as string[];
    const out: string[] = [];
    const start = new Date(seed.range.start + "T00:00:00Z");
    const end = new Date(seed.range.end + "T00:00:00Z");
    const cur = new Date(start);
    while (cur <= end) {
      out.push(cur.toISOString().slice(0, 10));
      cur.setUTCMonth(cur.getUTCMonth() + 1);
    }
    return out;
  }, [seed]);

  const systemTime = months[idx];

  const runReplay = useCallback(
    (sid: string, when: string) => {
      setReplayBusy(true);
      api
        .getReplay(sid, when)
        .then((r) => setReplay(r.beliefs))
        .catch(() => setReplay([]))
        .finally(() => setReplayBusy(false));
    },
    [],
  );

  // seed + load the four questions on mount
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const s = await api.seedDemo();
        if (!alive) return;
        setSeed(s);
        // start the slider just before the 2022 correction so the first drag flips it
        const startIdx = Math.max(
          0,
          Math.round(
            (new Date(s.range.superseded_at + "T00:00:00Z").getTime() -
              new Date(s.range.start + "T00:00:00Z").getTime()) /
              (1000 * 60 * 60 * 24 * 30.44),
          ) - 18,
        );
        setIdx(startIdx);
        const [ev, bt, dt] = await Promise.all([
          api.getEvent(s.session_id, "2020-06-01"),
          api.getTimeline(s.session_id, s.boston_belief_id),
          api.getTimeline(s.session_id, s.denver_belief_id),
        ]);
        if (!alive) return;
        setEvent2020(ev.beliefs);
        setBostonTl(bt);
        setDenverTl(dt);
      } catch {
        if (alive) setDown(true);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  // fetch replay whenever the slider settles
  useEffect(() => {
    if (!seed || !systemTime) return;
    if (debounce.current) clearTimeout(debounce.current);
    debounce.current = setTimeout(() => runReplay(seed.session_id, systemTime), 110);
    return () => {
      if (debounce.current) clearTimeout(debounce.current);
    };
  }, [seed, systemTime, runReplay]);

  if (down) {
    return (
      <div className="mb-10 flex items-start gap-3 rounded-2xl border border-warn/40 bg-warn/10 p-5 text-sm">
        <AlertTriangle className="mt-0.5 size-5 shrink-0 text-warn" />
        <div>
          <div className="font-semibold text-foreground">Replay needs the platform API</div>
          <p className="mt-1 text-muted-foreground">
            The replay is rendered live from the bi-temporal ledger, never faked. Start the API to
            see it: <code className="rounded bg-secondary px-1.5 py-0.5">python cogniflow-api/main.py</code>
          </p>
        </div>
      </div>
    );
  }

  const now = seed?.current ?? [];
  const nowCity = now[0] ? cityOf(now[0].statement) : " - ";
  const evCity = event2020[0] ? cityOf(event2020[0].statement) : " - ";
  const replayCity = replay[0] ? cityOf(replay[0].statement) : null;

  return (
    <section className="section-box mb-10 p-6 sm:p-8">
      <p className="eyebrow mb-2">The proof - system-time replay</p>
      <h2 className="text-section mb-2">What did the system believe, and when?</h2>
      <p className="text-subhead mb-6 max-w-[70ch]">
        A seeded scenario: Acme Corp&rsquo;s headquarters. The 2019 filing said <b>Boston</b>; the
        2022 filing said <b>Denver</b>. Drag the system-time slider to replay what the ledger knew at
        any past moment - the one thing plain RAG cannot do.
      </p>

      {/* Q1 + Q2: the two easy answers */}
      <div className="mb-6 grid gap-3 sm:grid-cols-2">
        <QuickAnswer label="Where is it now?" sub="event-time · today" city={nowCity} loading={!seed} />
        <QuickAnswer label="Where was it in 2020?" sub="event-time · as of 2020" city={evCity} loading={!seed} />
      </div>

      {/* Q3: the scrubber - the money shot */}
      <div className="ring-glow rounded-xl border border-brand/25 bg-card p-5 sm:p-6 elev">
        <div className="mb-4 flex items-center gap-2 text-sm font-semibold">
          <History className="size-4 text-brand" /> System-time replay
          {replayBusy && <Loader2 className="size-3.5 animate-spin text-brand" />}
        </div>

        <div className="mb-2 flex items-baseline justify-between">
          <span className="text-xs text-muted-foreground">The system knew, as of</span>
          <span className="font-display text-lg font-semibold tabular-nums">
            {systemTime ? monthLabel(systemTime) : " - "}
          </span>
        </div>

        {seed && months.length > 0 ? (
          <div className="relative">
            <input
              type="range"
              min={0}
              max={months.length - 1}
              step={1}
              value={idx}
              onChange={(e) => setIdx(Number(e.target.value))}
              className="w-full cursor-pointer accent-[var(--brand)]"
              aria-label="system time"
            />
            <div className="mt-1 flex justify-between text-[10px] uppercase tracking-wide text-muted-foreground">
              <span>{year(seed.range.start)}</span>
              <span className="text-brand">↑ 2022 correction</span>
              <span>{year(seed.range.end)}</span>
            </div>
          </div>
        ) : (
          <div className="h-6 animate-pulse rounded bg-secondary" />
        )}

        {/* the belief state, rendered verbatim from /api/audit/replay */}
        <div className="mt-5 min-h-[92px] rounded-lg border border-border bg-secondary/30 p-4">
          <AnimatePresence mode="wait">
            {replayCity ? (
              <motion.div
                key={replayCity}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -6 }}
                transition={{ duration: 0.25 }}
              >
                <div className="flex items-center gap-2 text-[15px]">
                  <MapPin className="size-4 text-brand" />
                  <span className="text-muted-foreground">Acme Corp is headquartered in</span>
                  <span className="font-display text-xl font-bold text-brand">{replayCity}</span>
                </div>
                <p className="mt-2 text-xs text-muted-foreground">
                  {replayCity === "Denver"
                    ? "After ingesting the 2022 press release."
                    : "It had not yet learned about the 2022 move - the later correction is un-known at this system-time."}
                </p>
                {replay[0] && (
                  <div className="mt-2 text-xs text-muted-foreground">
                    valid {ymd(replay[0].valid_at)} → {replay[0].invalid_at ? ymd(replay[0].invalid_at) : "present"}
                    {replay[0].provenance[0] && <> · source: {replay[0].provenance[0].display}</>}
                  </div>
                )}
              </motion.div>
            ) : (
              <motion.p
                key="empty"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="text-sm text-muted-foreground"
              >
                As of {systemTime ? monthLabel(systemTime) : "then"}, the system had not yet learned
                anything about Acme Corp.
              </motion.p>
            )}
          </AnimatePresence>
        </div>
      </div>

      {/* Q4: the full timeline + provenance */}
      <div className="mt-6">
        <div className="mb-3 flex items-center gap-2 text-sm font-semibold">
          <Clock className="size-4 text-brand" /> The fact&rsquo;s timeline &amp; citations
        </div>
        <div className="space-y-3">
          {bostonTl && <TimelineRow tl={bostonTl} superseded />}
          {denverTl && <TimelineRow tl={denverTl} />}
        </div>
      </div>

      <p className="mt-6 flex items-center gap-2 text-sm text-muted-foreground">
        <ArrowRight className="size-4 text-brand" />
        Plain RAG answers &ldquo;what is true now.&rdquo; This answers &ldquo;what did we believe
        then&rdquo; - and never leaks a later correction into the past.
      </p>
    </section>
  );
}

function QuickAnswer({ label, sub, city, loading }: { label: string; sub: string; city: string; loading: boolean }) {
  return (
    <div className="rounded-xl border border-border bg-card p-4 elev">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 flex items-center gap-2">
        <MapPin className="size-4 text-brand" />
        {loading ? (
          <span className="inline-block h-5 w-20 animate-pulse rounded bg-secondary" />
        ) : (
          <span className="font-display text-lg font-semibold">{city}</span>
        )}
      </div>
      <div className="mt-1 text-[11px] uppercase tracking-wide text-muted-foreground">{sub}</div>
    </div>
  );
}

function TimelineRow({ tl, superseded }: { tl: TimelineResponse; superseded?: boolean }) {
  const b = tl.belief;
  const ended = superseded && (b.invalid_at || b.superseded_by);
  const supEp = tl.trace.superseded_by_episode?.display;
  return (
    <div className={`rounded-lg border border-border bg-card p-4 ${ended ? "opacity-80" : ""}`}>
      <div className="flex flex-wrap items-center gap-2">
        <MapPin className={`size-4 ${ended ? "text-muted-foreground" : "text-brand"}`} />
        <span className={`text-[15px] ${ended ? "text-muted-foreground line-through" : "font-medium text-foreground"}`}>
          {b.statement}
        </span>
        {ended ? (
          <span className="ml-auto rounded-full border border-warn/30 bg-warn/10 px-2 py-0.5 text-[11px] font-medium text-warn">
            superseded
          </span>
        ) : (
          <span className="ml-auto rounded-full border border-win/30 bg-win/10 px-2 py-0.5 text-[11px] font-medium text-win">
            live
          </span>
        )}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span>valid {ymd(b.valid_at)} → {b.invalid_at ? ymd(b.invalid_at) : "present"}</span>
        {b.provenance[0] && <span>source: {b.provenance[0].display}</span>}
        {ended && supEp && <span>superseded by: {supEp}</span>}
      </div>
    </div>
  );
}
