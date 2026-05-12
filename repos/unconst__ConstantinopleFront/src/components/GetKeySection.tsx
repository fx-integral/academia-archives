import { motion } from 'framer-motion';
import { useState } from 'react';

export function GetKeySection() {
  const [revealed, setRevealed] = useState(false);

  return (
    <section id="get-key" className="relative py-32 px-8 lg:px-16">
      <div className="max-w-7xl mx-auto">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-16 items-start">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.6 }}
          >
            <div className="flex items-center gap-4 mb-6">
              <div className="w-5 h-px bg-g3-text-secondary" />
              <span className="font-sans text-xs text-g3-text-secondary tracking-widest uppercase">
                Instant access
              </span>
            </div>
            <h2 className="font-serif text-4xl sm:text-5xl text-g3-text leading-tight tracking-[-0.02em] mb-5">
              Get your key.
            </h2>
            <p className="font-sans text-base text-g3-text-secondary leading-relaxed max-w-md mb-10">
              No signup flow. Authenticate once and start building. Agents can create keys programmatically.
            </p>

            <div className="space-y-3 max-w-xs">
              {['GitHub', 'Email', 'Wallet'].map((provider) => (
                <button
                  key={provider}
                  className="flex items-center gap-3 w-full px-5 py-3.5 border border-white/[0.12] rounded-full font-sans text-sm text-g3-text-secondary hover:text-g3-text hover:border-white/30 hover:bg-white/[0.04] transition-all duration-300 tracking-wide"
                >
                  Continue with {provider}
                </button>
              ))}
            </div>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, x: 30 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.6, delay: 0.2 }}
            className="space-y-8"
          >
            <div>
              <div className="flex items-center gap-4 mb-4">
                <div className="w-5 h-px bg-g3-text-secondary" />
                <span className="font-sans text-xs text-g3-text-muted tracking-widest uppercase">
                  Your API key
                </span>
              </div>
              <div
                className="border border-white/[0.1] rounded-lg px-6 py-4 cursor-pointer hover:border-white/20 transition-colors duration-300"
                onClick={() => setRevealed(!revealed)}
              >
                <span className="font-mono text-sm text-g3-text">
                  {revealed ? 'cst-a8f3k2m9x7b1c4d6e5f0g1h2i3j4k5' : 'cst-••••••••••••••••••••••••'}
                </span>
                <span className="font-sans text-xs text-g3-text-muted ml-3">
                  {revealed ? 'hide' : 'reveal'}
                </span>
              </div>
            </div>

            <div>
              <div className="flex items-center gap-4 mb-4">
                <div className="w-5 h-px bg-g3-text-secondary" />
                <span className="font-sans text-xs text-g3-text-muted tracking-widest uppercase">
                  Try it now
                </span>
              </div>
              <div className="border border-white/[0.1] rounded-lg p-6">
                <pre className="font-mono text-[13px] text-g3-text-secondary leading-[1.8] overflow-x-auto whitespace-pre">{`curl https://api.constantinople.cloud/v1/chat/completions \\
  -H "Authorization: Bearer cst-your-key-here" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "Qwen/Qwen2.5-7B-Instruct",
    "messages": [{"role":"user","content":"hello"}]
  }'`}</pre>
              </div>
            </div>
          </motion.div>
        </div>
      </div>
    </section>
  );
}
