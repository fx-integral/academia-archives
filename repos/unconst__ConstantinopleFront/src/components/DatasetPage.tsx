import { motion, AnimatePresence } from 'framer-motion';
import { useEffect, useState, useCallback } from 'react';

const API_BASE = 'https://gateway.constantinople.cloud';

interface AuditChallenge {
  layer: number;
  token_pos: number;
  cosine_sim: number | null;
  latency_ms: number | null;
  passed: boolean;
}

interface AuditRecord {
  timestamp: string;
  request_id: string;
  type: 'organic' | 'synthetic';
  miner_uid: number;
  miner_hotkey: string;
  prompt: string;
  response: string;
  messages?: { role: string; content: string }[];
  ttft_ms: number;
  tokens_per_sec: number;
  input_tokens: number;
  output_tokens: number;
  speed_score: number;
  verification_score: number;
  quality_score: number;
  points_awarded: number;
  challenge?: AuditChallenge;
}

type DataSource = 'live' | 'history';

function timeAgo(iso: string): string {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return `${Math.floor(diff)}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function truncate(s: string, max: number): string {
  if (/^(tok_\d+\s*)+$/.test(s.trim())) return '[token IDs — pre-text logging]';
  return s.length > max ? s.slice(0, max) + '...' : s;
}

function formatDate(d: string): string {
  const [y, m, day] = d.split('-');
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  return `${months[parseInt(m)-1]} ${parseInt(day)}, ${y}`;
}

export function DatasetPage() {
  const [source, setSource] = useState<DataSource>('live');
  const [records, setRecords] = useState<AuditRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [filter, setFilter] = useState<'all' | 'organic' | 'synthetic' | 'challenged'>('all');

  // History-specific state
  const [availableDates, setAvailableDates] = useState<string[]>([]);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [nextToken, setNextToken] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);

  // Fetch available dates on mount
  useEffect(() => {
    fetch(`${API_BASE}/v1/audit/dates`, { signal: AbortSignal.timeout(8000) })
      .then(r => r.json())
      .then(data => {
        setAvailableDates(data.dates || []);
      })
      .catch(() => { /* dates listing is optional */ });
  }, []);

  // Fetch live data
  const fetchLive = useCallback(async () => {
    try {
      setLoading(true);
      const res = await fetch(`${API_BASE}/v1/audit/recent?limit=200`, { signal: AbortSignal.timeout(8000) });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setRecords(json.records || []);
      setTotal(json.total || 0);
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to fetch');
    } finally {
      setLoading(false);
    }
  }, []);

  // Fetch history data
  const fetchHistory = useCallback(async (date: string | null, append = false) => {
    try {
      if (append) setLoadingMore(true); else setLoading(true);
      const params = new URLSearchParams({ limit: '30' });
      if (date) params.set('date', date);
      if (append && nextToken) params.set('continuation_token', nextToken);

      const res = await fetch(`${API_BASE}/v1/audit/history?${params}`, { signal: AbortSignal.timeout(30000) });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();

      if (append) {
        setRecords(prev => [...prev, ...(json.records || [])]);
      } else {
        setRecords(json.records || []);
      }
      setTotal(json.total_keys || 0);
      setNextToken(json.next_token || null);
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to fetch');
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, [nextToken]);

  // Auto-fetch based on source
  useEffect(() => {
    if (source === 'live') {
      fetchLive();
      const interval = setInterval(fetchLive, 15000);
      return () => clearInterval(interval);
    } else {
      setNextToken(null);
      fetchHistory(selectedDate);
    }
  }, [source, selectedDate, fetchLive]);

  // Filter records
  const filtered = records.filter(r => {
    if (filter === 'organic') return r.type === 'organic';
    if (filter === 'synthetic') return r.type === 'synthetic';
    if (filter === 'challenged') return !!r.challenge;
    return true;
  });

  // Stats
  const totalTokens = records.reduce((s, r) => s + r.input_tokens + r.output_tokens, 0);
  const organicCount = records.filter(r => r.type === 'organic').length;
  const syntheticCount = records.filter(r => r.type === 'synthetic').length;
  const challengedCount = records.filter(r => !!r.challenge).length;
  const passedCount = records.filter(r => r.challenge?.passed).length;
  const avgTps = records.length > 0
    ? records.reduce((s, r) => s + r.tokens_per_sec, 0) / records.length
    : 0;

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.4 }}
      className="relative z-20 min-h-screen pt-28 pb-20 px-4 sm:px-8 lg:px-16"
    >
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="mb-12">
          <div className="flex items-center gap-4 mb-6">
            <div className="w-5 h-px bg-g3-text-secondary" />
            <span className="font-sans text-xs text-g3-text-secondary tracking-widest uppercase">
              Public inference dataset
            </span>
          </div>
          <h2 className="font-serif text-4xl sm:text-5xl text-g3-text leading-tight tracking-[-0.02em]">
            Every query, shared.
          </h2>
          <p className="font-sans text-base text-g3-text-secondary mt-4 max-w-lg leading-relaxed">
            All inference requests and hidden-state audits are logged to Cloudflare R2. This is the public record of intelligence flowing through Constantinople.
          </p>
        </div>

        {/* Source Tabs: Live vs History */}
        <div className="flex items-center gap-3 mb-6">
          <button
            onClick={() => setSource('live')}
            className={`px-5 py-2 rounded-full font-sans text-sm tracking-wide transition-colors ${
              source === 'live'
                ? 'bg-white/10 text-g3-text border border-white/20'
                : 'text-g3-text-muted hover:text-g3-text-secondary border border-transparent'
            }`}
          >
            Live Feed
          </button>
          <button
            onClick={() => setSource('history')}
            className={`px-5 py-2 rounded-full font-sans text-sm tracking-wide transition-colors ${
              source === 'history'
                ? 'bg-white/10 text-g3-text border border-white/20'
                : 'text-g3-text-muted hover:text-g3-text-secondary border border-transparent'
            }`}
          >
            R2 Archive
          </button>

          {/* Date picker for history mode */}
          {source === 'history' && availableDates.length > 0 && (
            <select
              value={selectedDate || ''}
              onChange={e => setSelectedDate(e.target.value || null)}
              className="ml-auto bg-white/[0.05] border border-white/[0.1] rounded-lg px-3 py-1.5 font-mono text-xs text-g3-text-secondary focus:outline-none focus:border-white/20"
            >
              <option value="">Today</option>
              {availableDates.map(d => (
                <option key={d} value={d}>{formatDate(d)}</option>
              ))}
            </select>
          )}
        </div>

        {/* Live Stats */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4 mb-10">
          <StatCard label="Total Records" value={source === 'live' ? total : records.length} />
          <StatCard label="Organic" value={organicCount} />
          <StatCard label="Synthetic" value={syntheticCount} />
          <StatCard label="Challenged" value={challengedCount} />
          <StatCard label="Passed" value={passedCount} color={passedCount > 0 ? 'text-emerald-400' : undefined} />
          <StatCard label="Avg TPS" value={Math.round(avgTps)} />
        </div>

        {/* Filter Tabs */}
        <div className="flex items-center gap-2 mb-6 flex-wrap">
          {(['all', 'organic', 'synthetic', 'challenged'] as const).map(f => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-4 py-1.5 rounded-full font-sans text-xs tracking-wide transition-colors ${
                filter === f
                  ? 'bg-white/10 text-g3-text border border-white/20'
                  : 'text-g3-text-muted hover:text-g3-text-secondary border border-transparent'
              }`}
            >
              {f === 'all' ? `All (${records.length})` :
               f === 'organic' ? `Organic (${organicCount})` :
               f === 'synthetic' ? `Synthetic (${syntheticCount})` :
               `Challenged (${challengedCount})`}
            </button>
          ))}
          {totalTokens > 0 && (
            <span className="ml-auto font-mono text-xs text-g3-text-muted">
              {totalTokens.toLocaleString()} tokens in view
            </span>
          )}
        </div>

        {/* Loading / Error States */}
        {loading && (
          <div className="text-center py-20">
            <div className="inline-block w-6 h-6 border-2 border-g3-text-muted border-t-transparent rounded-full animate-spin" />
            <p className="font-sans text-sm text-g3-text-muted mt-4">
              {source === 'history' ? 'Loading records from R2...' : 'Loading audit records...'}
            </p>
          </div>
        )}

        {error && !loading && (
          <div className="border border-red-500/20 rounded-lg p-6 bg-red-500/5">
            <p className="font-sans text-sm text-red-400">Failed to load audit data: {error}</p>
            <p className="font-sans text-xs text-red-400/60 mt-1">
              {source === 'live' ? 'Retrying every 15s' : 'Check gateway connectivity'}
            </p>
          </div>
        )}

        {/* Records List */}
        {!loading && filtered.length === 0 && !error && (
          <div className="text-center py-20">
            <p className="font-sans text-sm text-g3-text-muted">
              {source === 'history'
                ? `No records found for ${selectedDate ? formatDate(selectedDate) : 'today'}. Try selecting a different date.`
                : 'No records yet. The gateway will populate this as requests flow through.'}
            </p>
          </div>
        )}

        {!loading && filtered.length > 0 && (
          <div className="space-y-2">
            {filtered.map((r) => (
              <RecordRow
                key={r.request_id}
                record={r}
                expanded={expanded === r.request_id}
                onToggle={() => setExpanded(expanded === r.request_id ? null : r.request_id)}
              />
            ))}
          </div>
        )}

        {/* Load More (history mode with pagination) */}
        {source === 'history' && nextToken && !loading && (
          <div className="mt-8 text-center">
            <button
              onClick={() => fetchHistory(selectedDate, true)}
              disabled={loadingMore}
              className="px-6 py-2.5 border border-white/20 rounded-full font-sans text-sm text-g3-text hover:bg-white/10 transition-colors disabled:opacity-50"
            >
              {loadingMore ? 'Loading...' : 'Load more records'}
            </button>
          </div>
        )}
      </div>
    </motion.div>
  );
}

function RecordRow({ record: r, expanded, onToggle }: { record: AuditRecord; expanded: boolean; onToggle: () => void }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 5 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className="border border-white/[0.08] rounded-lg overflow-hidden backdrop-blur-sm bg-white/[0.02]"
    >
      {/* Row Summary */}
      <button
        onClick={onToggle}
        className="w-full text-left px-4 sm:px-5 py-3.5 flex items-center gap-3 hover:bg-white/[0.03] transition-colors"
      >
        {/* Type Badge */}
        <span className={`shrink-0 inline-flex items-center px-2 py-0.5 rounded text-[10px] font-mono tracking-wider uppercase ${
          r.type === 'organic'
            ? 'bg-blue-500/15 text-blue-400'
            : 'bg-purple-500/15 text-purple-400'
        }`}>
          {r.type}
        </span>

        {/* Challenge indicator */}
        {r.challenge && (
          <span className={`shrink-0 w-1.5 h-1.5 rounded-full ${r.challenge.passed ? 'bg-emerald-400' : 'bg-red-400'}`}
            title={r.challenge.passed ? 'Challenge passed' : 'Challenge failed'} />
        )}

        {/* Prompt preview */}
        <span className="flex-1 font-sans text-sm text-g3-text-secondary truncate min-w-0">
          {truncate(r.prompt || (r.messages?.[r.messages.length - 1]?.content ?? ''), 80)}
        </span>

        {/* Miner UID */}
        <span className="shrink-0 font-mono text-xs text-g3-text-muted">
          UID {r.miner_uid}
        </span>

        {/* Time */}
        <span className="shrink-0 font-mono text-xs text-g3-text-muted w-16 text-right">
          {timeAgo(r.timestamp)}
        </span>

        {/* Expand chevron */}
        <svg className={`shrink-0 w-4 h-4 text-g3-text-muted transition-transform ${expanded ? 'rotate-180' : ''}`}
          viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>

      {/* Expanded Detail */}
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="px-4 sm:px-5 pb-5 border-t border-white/[0.06] pt-4 space-y-4">
              {/* Prompt */}
              <div>
                <label className="font-sans text-[11px] text-g3-text-muted tracking-wider uppercase mb-1.5 block">Prompt</label>
                <div className="font-mono text-sm text-g3-text-secondary bg-black/20 rounded p-3 max-h-40 overflow-y-auto whitespace-pre-wrap break-words">
                  {r.messages
                    ? r.messages.map((m, i) => (
                        <div key={i} className={`${i > 0 ? 'mt-2 pt-2 border-t border-white/[0.06]' : ''}`}>
                          <span className="text-g3-text-muted text-[11px] uppercase">{m.role}:</span>
                          <span className="ml-2">{m.content}</span>
                        </div>
                      ))
                    : r.prompt}
                </div>
              </div>

              {/* Response */}
              <div>
                <label className="font-sans text-[11px] text-g3-text-muted tracking-wider uppercase mb-1.5 block">Response</label>
                <div className="font-mono text-sm text-g3-text-secondary bg-black/20 rounded p-3 max-h-60 overflow-y-auto whitespace-pre-wrap break-words">
                  {/^(tok_\d+\s*)+$/.test(r.response.trim())
                    ? <span className="text-g3-text-muted italic">Token IDs only (pre-text logging)</span>
                    : r.response}
                </div>
              </div>

              {/* Metrics Grid */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <MiniMetric label="TTFT" value={`${r.ttft_ms.toFixed(0)}ms`} />
                <MiniMetric label="Speed" value={`${r.tokens_per_sec.toFixed(0)} tok/s`} />
                <MiniMetric label="Input" value={`${r.input_tokens} tok`} />
                <MiniMetric label="Output" value={`${r.output_tokens} tok`} />
                <MiniMetric label="Speed Score" value={r.speed_score.toFixed(3)} />
                <MiniMetric label="Verify Score" value={r.verification_score.toFixed(3)} />
                <MiniMetric label="Quality" value={r.quality_score.toFixed(3)} />
                <MiniMetric label="Points" value={r.points_awarded.toFixed(2)} />
              </div>

              {/* Challenge Detail */}
              {r.challenge && (
                <div className="border border-white/[0.06] rounded-lg p-3">
                  <div className="flex items-center gap-2 mb-2">
                    <span className={`w-1.5 h-1.5 rounded-full ${r.challenge.passed ? 'bg-emerald-400' : 'bg-red-400'}`} />
                    <span className="font-sans text-xs text-g3-text">
                      Hidden State Challenge — {r.challenge.passed ? 'Passed' : 'Failed'}
                    </span>
                  </div>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    <MiniMetric label="Layer" value={`${r.challenge.layer}`} />
                    <MiniMetric label="Token Pos" value={`${r.challenge.token_pos}`} />
                    <MiniMetric label="Cosine Sim" value={r.challenge.cosine_sim?.toFixed(6) ?? '—'} />
                    <MiniMetric label="Latency" value={r.challenge.latency_ms ? `${r.challenge.latency_ms.toFixed(0)}ms` : '—'} />
                  </div>
                </div>
              )}

              {/* Request ID */}
              <div className="flex items-center gap-2 pt-1">
                <span className="font-mono text-[10px] text-g3-text-muted">
                  {r.request_id}
                </span>
                <span className="font-mono text-[10px] text-g3-text-muted">
                  · {new Date(r.timestamp).toLocaleString()}
                </span>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

function StatCard({ label, value, color }: { label: string; value: number; color?: string }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="border border-white/[0.08] rounded-lg p-4"
    >
      <div className={`font-mono text-xl font-semibold mb-0.5 ${color ?? 'text-g3-text'}`}>
        {value.toLocaleString()}
      </div>
      <div className="font-sans text-[11px] text-g3-text-muted tracking-wider uppercase">{label}</div>
    </motion.div>
  );
}

function MiniMetric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="font-mono text-sm text-g3-text">{value}</div>
      <div className="font-sans text-[10px] text-g3-text-muted tracking-wider uppercase">{label}</div>
    </div>
  );
}
