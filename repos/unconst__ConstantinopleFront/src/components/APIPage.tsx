import { motion } from 'framer-motion';
import { useEffect, useState, useCallback } from 'react';

const API_BACKEND = import.meta.env.VITE_API_BACKEND || 'https://api.constantinople.cloud';

interface UserInfo {
  id: number;
  email: string;
  name: string;
  balance: number;
  tier: string;
}

interface APIKey {
  id: number;
  key_prefix: string;
  name: string;
  created_at: string;
  last_used_at: string | null;
  is_active: number;
}

interface UsageDay {
  date: string;
  input_tokens: number;
  output_tokens: number;
  requests: number;
  cost: number;
}

type CodeLang = 'python' | 'curl' | 'javascript';

export function APIPage() {
  const [user, setUser] = useState<UserInfo | null>(null);
  const [keys, setKeys] = useState<APIKey[]>([]);
  const [usage, setUsage] = useState<UsageDay[]>([]);
  const [totalUsage, setTotalUsage] = useState({ requests: 0, cost: 0, inputTokens: 0, outputTokens: 0 });
  const [newKey, setNewKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [invoice, setInvoice] = useState<{ amount: string; currency: string; address: string; id: string } | null>(null);
  const [taoDeposit, setTaoDeposit] = useState<{ address: string; price: number; rate: string } | null>(null);
  const [taoLoading, setTaoLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [codeLang, setCodeLang] = useState<CodeLang>('python');

  // Form state
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [isLogin, setIsLogin] = useState(false);

  // Stored API key for session
  const [sessionKey, setSessionKey] = useState<string>(() => {
    try { return localStorage.getItem('cst_api_key') || ''; }
    catch { return ''; }
  });

  const saveSessionKey = (key: string) => {
    setSessionKey(key);
    try { localStorage.setItem('cst_api_key', key); } catch {}
  };

  const fetchDashboard = useCallback(async () => {
    if (!sessionKey) return;
    try {
      const headers = { 'Authorization': `Bearer ${sessionKey}` };

      const [balRes, usageRes, keysRes] = await Promise.all([
        fetch(`${API_BACKEND}/v1/user/balance`, { headers }),
        fetch(`${API_BACKEND}/v1/user/usage?days=30`, { headers }),
        fetch(`${API_BACKEND}/v1/keys`, { headers }),
      ]);

      if (!balRes.ok) {
        if (balRes.status === 401) {
          setError('Invalid API key. Please log in again.');
          saveSessionKey('');
          return;
        }
        throw new Error('Failed to fetch');
      }

      const balData = await balRes.json();
      const usageData = await usageRes.json();
      const keysData = await keysRes.json();

      setUser({ ...(user || { id: 0, email: '', name: '' }), balance: balData.balance, tier: balData.tier });
      setUsage(usageData.daily || []);
      setTotalUsage({
        requests: usageData.total_requests,
        cost: usageData.total_cost,
        inputTokens: usageData.total_input_tokens,
        outputTokens: usageData.total_output_tokens,
      });
      setKeys(keysData);
    } catch {
      setError('Failed to load dashboard data');
    }
  }, [sessionKey, user]);

  useEffect(() => {
    if (sessionKey) {
      fetchDashboard();
    }
  }, [sessionKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleAuth = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      if (isLogin) {
        const res = await fetch(`${API_BACKEND}/v1/auth/login`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email, password }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Login failed');

        setUser(data.user);
        setKeys(data.api_keys || []);
        if (data.session_key) {
          saveSessionKey(data.session_key);
        } else {
          setError('Logged in. Enter one of your API keys below to access the dashboard.');
        }
      } else {
        const res = await fetch(`${API_BACKEND}/v1/auth/register`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email, password, name: name || undefined }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Registration failed');

        setUser(data.user);
        setNewKey(data.api_key.key);
        saveSessionKey(data.api_key.key);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Something went wrong');
    } finally {
      setLoading(false);
    }
  };

  const handleCreateKey = async () => {
    setError(null);
    try {
      const res = await fetch(`${API_BACKEND}/v1/keys/create`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${sessionKey}`,
        },
        body: JSON.stringify({ name: `key-${Date.now()}` }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed to create key');

      setNewKey(data.key);
      fetchDashboard();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed');
    }
  };

  const handleRevokeKey = async (keyId: number) => {
    try {
      const res = await fetch(`${API_BACKEND}/v1/keys/${keyId}`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${sessionKey}` },
      });
      if (res.ok) {
        fetchDashboard();
      } else {
        const data = await res.json().catch(() => null);
        setError(data?.detail || 'Failed to revoke key');
      }
    } catch {}
  };

  const handleLogout = () => {
    saveSessionKey('');
    setUser(null);
    setKeys([]);
    setNewKey(null);
  };

  const codeExamples: Record<CodeLang, { label: string; code: string }> = {
    python: {
      label: 'Python',
      code: `from openai import OpenAI

client = OpenAI(
    base_url="${API_BACKEND}/v1",
    api_key="${sessionKey || 'cst-your-key-here'}"
)

response = client.chat.completions.create(
    model="Qwen/Qwen2.5-7B-Instruct",
    messages=[{"role": "user", "content": "What is Constantinople?"}],
    max_tokens=200,
)
print(response.choices[0].message.content)`,
    },
    curl: {
      label: 'cURL',
      code: `curl ${API_BACKEND}/v1/chat/completions \\
  -H "Authorization: Bearer ${sessionKey || 'cst-your-key-here'}" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "Qwen/Qwen2.5-7B-Instruct",
    "messages": [{"role": "user", "content": "Hello!"}],
    "max_tokens": 100
  }'`,
    },
    javascript: {
      label: 'JavaScript',
      code: `import OpenAI from 'openai';

const client = new OpenAI({
  baseURL: '${API_BACKEND}/v1',
  apiKey: '${sessionKey || 'cst-your-key-here'}',
});

const completion = await client.chat.completions.create({
  model: 'Qwen/Qwen2.5-7B-Instruct',
  messages: [{ role: 'user', content: 'What is decentralized inference?' }],
});
console.log(completion.choices[0].message.content);`,
    },
  };

  // ─── Not logged in: sign up / sign in ───
  if (!sessionKey) {
    return (
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="pt-28 pb-20 px-6 lg:px-16 max-w-5xl mx-auto"
      >
        <h1 className="font-serif text-3xl text-g3-text mb-2">API Access</h1>
        <p className="text-g3-text-secondary text-sm mb-8">
          Get an API key to access the Constantinople inference network. OpenAI-compatible endpoints.
        </p>

        {error && (
          <div className="mb-6 p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-300 text-sm">
            {error}
            <button onClick={() => setError(null)} className="ml-2 text-red-400 hover:text-red-300">x</button>
          </div>
        )}

        <div className="max-w-md">
          <h2 className="font-serif text-xl text-g3-text mb-4">{isLogin ? 'Sign In' : 'Create Account'}</h2>
          <form onSubmit={handleAuth} className="space-y-4">
            {!isLogin && (
              <input
                type="text"
                placeholder="Name (optional)"
                value={name}
                onChange={e => setName(e.target.value)}
                className="w-full px-4 py-3 bg-white/[0.04] border border-white/[0.08] rounded-lg text-g3-text placeholder:text-g3-text-secondary/50 focus:outline-none focus:border-white/20 text-sm"
              />
            )}
            <input
              type="email"
              placeholder="Email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              required
              className="w-full px-4 py-3 bg-white/[0.04] border border-white/[0.08] rounded-lg text-g3-text placeholder:text-g3-text-secondary/50 focus:outline-none focus:border-white/20 text-sm"
            />
            <input
              type="password"
              placeholder="Password (min 8 characters)"
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
              minLength={8}
              className="w-full px-4 py-3 bg-white/[0.04] border border-white/[0.08] rounded-lg text-g3-text placeholder:text-g3-text-secondary/50 focus:outline-none focus:border-white/20 text-sm"
            />
            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 bg-white/10 hover:bg-white/15 border border-white/20 rounded-lg font-sans text-sm text-g3-text transition-all disabled:opacity-50"
            >
              {loading ? '...' : isLogin ? 'Sign In' : 'Create Account & Get API Key'}
            </button>
          </form>
          <button
            onClick={() => { setIsLogin(!isLogin); setError(null); }}
            className="mt-4 text-sm text-g3-text-secondary hover:text-g3-text transition-colors"
          >
            {isLogin ? "Don't have an account? Sign up" : 'Already have an account? Sign in'}
          </button>

          <div className="mt-6 p-4 bg-white/[0.02] border border-white/[0.06] rounded-lg">
            <p className="text-sm text-g3-text-secondary mb-1">Or enter an existing API key:</p>
            <div className="flex gap-2">
              <input
                type="text"
                placeholder="cst-..."
                className="flex-1 px-3 py-2 bg-white/[0.04] border border-white/[0.08] rounded-lg text-g3-text text-sm font-mono focus:outline-none focus:border-white/20"
                onKeyDown={e => {
                  if (e.key === 'Enter') {
                    const val = (e.target as HTMLInputElement).value.trim();
                    if (val) saveSessionKey(val);
                  }
                }}
              />
              <button
                onClick={() => {
                  const input = document.querySelector('input[placeholder="cst-..."]') as HTMLInputElement;
                  if (input?.value.trim()) saveSessionKey(input.value.trim());
                }}
                className="px-4 py-2 bg-white/10 border border-white/20 rounded-lg text-sm text-g3-text hover:bg-white/15 transition-colors"
              >
                Connect
              </button>
            </div>
          </div>

          <div className="mt-8 p-4 bg-white/[0.02] border border-white/[0.06] rounded-lg">
            <h3 className="text-sm font-semibold text-g3-text mb-2">Free Tier</h3>
            <p className="text-sm text-g3-text-secondary">
              Sign up and get <span className="text-g3-text">1.0 free credits</span> instantly.
              That's enough for ~666K input tokens or ~666K output tokens with Qwen 7B.
            </p>
            <div className="mt-3 grid grid-cols-2 gap-4 text-xs text-g3-text-secondary">
              <div>
                <div className="text-g3-text font-mono">$0.50</div>
                <div>per 1M input tokens</div>
              </div>
              <div>
                <div className="text-g3-text font-mono">$1.50</div>
                <div>per 1M output tokens</div>
              </div>
            </div>
          </div>
        </div>
      </motion.div>
    );
  }

  // ─── Logged in: single dashboard + quick start ───
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="pt-28 pb-20 px-6 lg:px-16 max-w-5xl mx-auto"
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="font-serif text-3xl text-g3-text mb-1">Dashboard</h1>
          <p className="text-g3-text-secondary text-sm">
            {user?.email || 'Your account'} &middot; <span className="font-mono">${(user?.balance ?? 0).toFixed(2)}</span> credits
          </p>
        </div>
        <button
          onClick={handleLogout}
          className="px-4 py-2 text-sm text-g3-text-secondary hover:text-red-400 border border-white/[0.08] rounded-lg transition-colors"
        >
          Logout
        </button>
      </div>

      {error && (
        <div className="mb-6 p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-300 text-sm">
          {error}
          <button onClick={() => setError(null)} className="ml-2 text-red-400 hover:text-red-300">x</button>
        </div>
      )}

      {newKey && (
        <div className="mb-6 p-4 bg-emerald-500/10 border border-emerald-500/30 rounded-lg">
          <p className="text-sm text-emerald-300 mb-2 font-semibold">Save your API key now — it won't be shown again:</p>
          <div className="flex items-center gap-2">
            <code className="flex-1 px-3 py-2 bg-black/30 rounded font-mono text-sm text-g3-text break-all select-all">
              {newKey}
            </code>
            <button
              onClick={() => { navigator.clipboard.writeText(newKey); }}
              className="px-3 py-2 bg-white/10 border border-white/20 rounded text-sm text-g3-text hover:bg-white/15"
            >
              Copy
            </button>
          </div>
          <button onClick={() => setNewKey(null)} className="mt-2 text-xs text-g3-text-secondary hover:text-g3-text">
            Dismiss
          </button>
        </div>
      )}

      <div className="space-y-6">
        {/* Quick Start — tabbed code examples */}
        <div className="p-5 bg-white/[0.02] border border-white/[0.06] rounded-lg">
          <h3 className="text-sm font-semibold text-g3-text mb-1">Quick Start</h3>
          <p className="text-xs text-g3-text-secondary mb-4">
            OpenAI-compatible API. Use any OpenAI SDK or HTTP client.
          </p>

          {/* Language tabs */}
          <div className="flex gap-1 mb-3 border-b border-white/[0.08] pb-px">
            {(['python', 'curl', 'javascript'] as CodeLang[]).map(lang => (
              <button
                key={lang}
                onClick={() => setCodeLang(lang)}
                className={`px-3 py-1.5 text-xs font-mono transition-colors border-b-2 -mb-px ${
                  codeLang === lang
                    ? 'text-g3-text border-white/40'
                    : 'text-g3-text-secondary border-transparent hover:text-g3-text'
                }`}
              >
                {codeExamples[lang].label}
              </button>
            ))}
          </div>
          <CodeBlock code={codeExamples[codeLang].code} />
        </div>

        {/* API Keys — compact */}
        <div className="p-5 bg-white/[0.02] border border-white/[0.06] rounded-lg">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-g3-text">Your Keys</h3>
            <button
              onClick={handleCreateKey}
              className="px-3 py-1.5 bg-white/10 border border-white/20 rounded text-xs text-g3-text hover:bg-white/15 transition-colors"
            >
              + New Key
            </button>
          </div>
          {keys.length === 0 ? (
            <p className="text-sm text-g3-text-secondary">No API keys yet.</p>
          ) : (
            <div className="space-y-2">
              {keys.map(k => (
                <div key={k.id} className="flex items-center justify-between p-2 bg-white/[0.02] rounded">
                  <div className="flex items-center gap-3">
                    <code className="text-sm font-mono text-g3-text">{k.key_prefix}</code>
                    <span className="text-xs text-g3-text-secondary">{k.name}</span>
                    <span className={`text-xs ${k.is_active ? 'text-emerald-400' : 'text-red-400'}`}>
                      {k.is_active ? 'Active' : 'Revoked'}
                    </span>
                  </div>
                  {k.is_active ? (
                    <button
                      onClick={() => handleRevokeKey(k.id)}
                      className="text-xs text-red-400/70 hover:text-red-400 transition-colors"
                    >
                      Revoke
                    </button>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Usage + Credits side by side on desktop */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Usage */}
          <div className="p-5 bg-white/[0.02] border border-white/[0.06] rounded-lg">
            <h3 className="text-sm font-semibold text-g3-text mb-3">Usage (30 Days)</h3>
            <div className="grid grid-cols-2 gap-3 mb-3">
              <StatCard label="Requests" value={totalUsage.requests.toLocaleString()} />
              <StatCard label="Cost" value={`$${totalUsage.cost.toFixed(4)}`} />
            </div>
            {usage.length > 0 && (
              <div className="space-y-1">
                {usage.slice(0, 7).map(d => {
                  const maxReqs = Math.max(...usage.map(u => u.requests), 1);
                  const pct = (d.requests / maxReqs) * 100;
                  return (
                    <div key={d.date} className="flex items-center gap-2 text-xs">
                      <span className="w-14 text-g3-text-secondary font-mono">{d.date.slice(5)}</span>
                      <div className="flex-1 bg-white/[0.04] rounded-full h-1.5 overflow-hidden">
                        <div className="h-full bg-white/20 rounded-full" style={{ width: `${pct}%` }} />
                      </div>
                      <span className="w-10 text-right text-g3-text-secondary">{d.requests}</span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Add Credits */}
          <div className="p-5 bg-white/[0.02] border border-white/[0.06] rounded-lg">
            <h3 className="text-sm font-semibold text-g3-text mb-3">Add Credits</h3>
            <p className="text-xs text-g3-text-secondary mb-3">1 credit = $1 USD &middot; Pay with TAO, USDC, or ETH</p>

            {/* TAO Payment */}
            <p className="text-xs text-g3-text-secondary uppercase tracking-wider mb-2">TAO on Bittensor</p>
            <div className="mb-4">
              {!taoDeposit ? (
                <button
                  disabled={taoLoading}
                  className="px-4 py-2 bg-white/[0.06] border border-white/[0.12] rounded-lg text-xs text-g3-text hover:bg-white/10 hover:border-white/20 transition-all disabled:opacity-50"
                  onClick={async () => {
                    setTaoLoading(true); setError(null);
                    try {
                      const res = await fetch(`${API_BACKEND}/v1/billing/tao-deposit`, {
                        headers: { 'Authorization': `Bearer ${sessionKey}` },
                      });
                      const data = await res.json();
                      if (!res.ok) throw new Error(data.detail || 'Failed');
                      setTaoDeposit({ address: data.deposit_address, price: data.tao_usd_price, rate: data.rate });
                    } catch (err: unknown) {
                      setError(err instanceof Error ? err.message : 'Failed to get TAO deposit address');
                    } finally {
                      setTaoLoading(false);
                    }
                  }}
                >
                  {taoLoading ? 'Loading...' : 'Get TAO Deposit Address'}
                </button>
              ) : (
                <div className="p-3 bg-amber-500/10 border border-amber-500/30 rounded-lg">
                  <div className="flex items-start justify-between mb-2">
                    <p className="text-sm text-amber-300 font-semibold">Your TAO Deposit Address</p>
                    <button onClick={() => setTaoDeposit(null)} className="text-amber-400 hover:text-amber-300 text-xs">dismiss</button>
                  </div>
                  <div className="flex items-center gap-2 mb-2">
                    <code className="flex-1 px-3 py-2 bg-black/30 rounded font-mono text-xs text-g3-text break-all select-all">{taoDeposit.address}</code>
                    <button
                      onClick={() => { navigator.clipboard?.writeText(taoDeposit.address).catch(() => {}); }}
                      className="px-2 py-2 text-xs bg-white/[0.06] border border-white/[0.12] rounded hover:bg-white/10 text-g3-text-secondary"
                    >Copy</button>
                  </div>
                  <p className="text-xs text-g3-text-secondary">
                    Current rate: <span className="text-g3-text font-mono">{taoDeposit.rate}</span>
                  </p>
                  <p className="text-xs text-g3-text-secondary mt-1">
                    Send any amount of TAO. Credits added automatically within 60 seconds at the rate when your deposit is detected.
                  </p>
                </div>
              )}
            </div>

            <p className="text-xs text-g3-text-secondary uppercase tracking-wider mb-2">USDC on Base</p>
            <div className="flex gap-2 flex-wrap mb-4">
              {[5, 10, 25, 100].map(amt => (
                <button
                  key={amt}
                  className="px-3 py-1.5 bg-white/[0.06] border border-white/[0.12] rounded-lg text-xs text-g3-text hover:bg-white/10 hover:border-white/20 transition-all"
                  onClick={async () => {
                    setError(null); setInvoice(null);
                    try {
                      const res = await fetch(`${API_BACKEND}/v1/billing/topup`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${sessionKey}` },
                        body: JSON.stringify({ amount: amt, payment_method: 'crypto', currency: 'USDC' }),
                      });
                      const data = await res.json();
                      if (!res.ok) throw new Error(data.detail || 'Failed');
                      setInvoice({ amount: `$${data.amount_usd}`, currency: 'USDC', address: data.deposit_address, id: data.invoice_id });
                    } catch (err: unknown) {
                      setError(err instanceof Error ? err.message : 'Payment failed');
                    }
                  }}
                >
                  ${amt}
                </button>
              ))}
            </div>

            <p className="text-xs text-g3-text-secondary uppercase tracking-wider mb-2">ETH on Base</p>
            <div className="flex gap-2 flex-wrap">
              {[5, 10, 25, 100].map(amt => (
                <button
                  key={`eth-${amt}`}
                  className="px-3 py-1.5 bg-white/[0.06] border border-white/[0.12] rounded-lg text-xs text-g3-text hover:bg-white/10 hover:border-white/20 transition-all"
                  onClick={async () => {
                    setError(null); setInvoice(null);
                    try {
                      const res = await fetch(`${API_BACKEND}/v1/billing/topup`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${sessionKey}` },
                        body: JSON.stringify({ amount: amt, payment_method: 'crypto', currency: 'ETH' }),
                      });
                      const data = await res.json();
                      if (!res.ok) throw new Error(data.detail || 'Failed');
                      setInvoice({ amount: `$${data.amount_usd}`, currency: 'ETH', address: data.deposit_address, id: data.invoice_id });
                    } catch (err: unknown) {
                      setError(err instanceof Error ? err.message : 'Payment failed');
                    }
                  }}
                >
                  ${amt}
                </button>
              ))}
            </div>

            {invoice && (
              <div className="mt-4 p-4 bg-blue-500/10 border border-blue-500/30 rounded-lg">
                <div className="flex items-start justify-between">
                  <p className="text-sm text-blue-300 font-semibold mb-2">Payment Invoice</p>
                  <button onClick={() => setInvoice(null)} className="text-blue-400 hover:text-blue-300 text-xs">dismiss</button>
                </div>
                <p className="text-xs text-g3-text-secondary mb-2">
                  Send exactly <span className="text-g3-text font-mono font-semibold">{invoice.amount}</span> {invoice.currency} on <span className="text-g3-text">Base</span> to:
                </p>
                <div className="flex items-center gap-2 mb-2">
                  <code className="flex-1 px-3 py-2 bg-black/30 rounded font-mono text-xs text-g3-text break-all select-all">{invoice.address}</code>
                  <button
                    onClick={() => { navigator.clipboard?.writeText(invoice.address).catch(() => { const ta = document.createElement('textarea'); ta.value = invoice.address; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta); }); }}
                    className="px-2 py-2 text-xs bg-white/[0.06] border border-white/[0.12] rounded hover:bg-white/10 text-g3-text-secondary"
                  >Copy</button>
                </div>
                <p className="text-xs text-g3-text-secondary">Auto-confirmed after ~3 block confirmations (~6 seconds). Invoice ID: <span className="font-mono">{invoice.id}</span></p>
              </div>
            )}
          </div>
        </div>

        {/* Endpoints — collapsed by default */}
        <details className="p-5 bg-white/[0.02] border border-white/[0.06] rounded-lg">
          <summary className="text-sm font-semibold text-g3-text cursor-pointer select-none">Endpoints Reference</summary>
          <div className="mt-3 space-y-2 text-sm">
            <EndpointRow method="POST" path="/v1/chat/completions" desc="Chat completions (OpenAI-compatible)" />
            <EndpointRow method="POST" path="/v1/completions" desc="Text completions" />
            <EndpointRow method="POST" path="/v1/embeddings" desc="Text embeddings" />
            <EndpointRow method="GET" path="/v1/models" desc="List available models" />
            <EndpointRow method="GET" path="/v1/user/balance" desc="Check credit balance" />
            <EndpointRow method="GET" path="/v1/user/usage" desc="Usage analytics" />
            <EndpointRow method="GET" path="/v1/pricing" desc="Current pricing" />
          </div>
        </details>
      </div>
    </motion.div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="p-3 bg-white/[0.02] border border-white/[0.06] rounded-lg">
      <div className="text-xs text-g3-text-secondary mb-1">{label}</div>
      <div className="text-lg font-mono text-g3-text">{value}</div>
    </div>
  );
}

function CodeBlock({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
    } catch {
      const ta = document.createElement('textarea');
      ta.value = code;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      setCopied(true);
    }
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <div className="relative group">
      <pre className="p-3 pr-16 bg-black/30 rounded-lg overflow-x-auto text-xs font-mono text-g3-text-secondary leading-relaxed select-text">{code}</pre>
      <button
        onClick={handleCopy}
        className="absolute top-2 right-2 px-2 py-1 bg-white/10 rounded text-xs text-g3-text-secondary hover:bg-white/20 hover:text-g3-text transition-colors"
      >
        {copied ? 'Copied!' : 'Copy'}
      </button>
    </div>
  );
}

function EndpointRow({ method, path, desc }: { method: string; path: string; desc: string }) {
  const color = method === 'GET' ? 'text-emerald-400' : 'text-blue-400';
  return (
    <div className="flex items-center gap-3">
      <span className={`w-12 text-xs font-mono font-bold ${color}`}>{method}</span>
      <code className="text-g3-text font-mono text-xs">{path}</code>
      <span className="text-g3-text-secondary text-xs">— {desc}</span>
    </div>
  );
}
