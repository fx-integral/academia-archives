import { motion } from 'framer-motion';
import { useState } from 'react';

const tabs = ['Python', 'curl'] as const;

const codeExamples: Record<(typeof tabs)[number], string> = {
  Python: `from openai import OpenAI

client = OpenAI(
    base_url="https://api.constantinople.cloud/v1",
    api_key="cst-your-key-here",
)

for chunk in client.chat.completions.create(
    model="Qwen/Qwen2.5-7B-Instruct",
    messages=[{"role": "user", "content": "Hello!"}],
    stream=True,
):
    print(chunk.choices[0].delta.content or "", end="")`,

  curl: `curl https://api.constantinople.cloud/v1/chat/completions \\
  -H "Authorization: Bearer cst-your-key-here" \\
  -H 'Content-Type: application/json' \\
  -d '{
    "model": "Qwen/Qwen2.5-7B-Instruct",
    "messages": [
      {"role": "user", "content": "Hello!"}
    ],
    "stream": true
  }'`,
};

export function APISection() {
  const [activeTab, setActiveTab] = useState<(typeof tabs)[number]>('Python');

  return (
    <section id="api" className="relative py-32 px-8 lg:px-16">
      <div className="max-w-7xl mx-auto">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.6 }}
          className="mb-16"
        >
          <div className="flex items-center gap-4 mb-6">
            <div className="w-5 h-px bg-g3-text-secondary" />
            <span className="font-sans text-xs text-g3-text-secondary tracking-widest uppercase">
              OpenAI compatible
            </span>
          </div>
          <h2 className="font-serif text-4xl sm:text-5xl text-g3-text leading-tight tracking-[-0.02em] max-w-2xl">
            One model. One endpoint.
          </h2>
          <p className="font-sans text-base text-g3-text-secondary mt-4 max-w-lg leading-relaxed">
            Blazing fast, always-on, agentic inference which you share: every query is first sanitized and then made public.
          </p>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5, delay: 0.1 }}
          className="max-w-3xl"
        >
          <div className="border border-white/[0.1] rounded-lg overflow-hidden">
            <div className="flex border-b border-white/[0.08]">
              {tabs.map((tab) => (
                <button
                  key={tab}
                  onClick={() => setActiveTab(tab)}
                  className={`px-5 py-3 font-sans text-xs tracking-wide transition-colors duration-200 ${
                    activeTab === tab
                      ? 'text-g3-text border-b border-g3-accent'
                      : 'text-g3-text-muted hover:text-g3-text-secondary'
                  }`}
                >
                  {tab}
                </button>
              ))}
            </div>
            <div className="p-6 overflow-x-auto">
              <pre className="font-mono text-[13px] leading-[1.8] text-g3-text-secondary whitespace-pre">
                {codeExamples[activeTab]}
              </pre>
            </div>
          </div>
        </motion.div>

        <motion.div
          initial={{ opacity: 0 }}
          whileInView={{ opacity: 1 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5, delay: 0.3 }}
          className="mt-10 flex flex-col sm:flex-row sm:items-center gap-4"
        >
          <div className="flex items-center gap-3">
            <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            <span className="font-sans text-sm text-g3-text-secondary">
              constantinople
            </span>
          </div>
          <span className="font-sans text-sm text-g3-text-muted">·</span>
          <span className="font-sans text-sm text-g3-text-muted">
            Free tier — 1.0 credits on signup
          </span>
          <span className="font-sans text-sm text-g3-text-muted">·</span>
          <span className="font-sans text-sm text-g3-text-muted">
            Streaming supported
          </span>
        </motion.div>
      </div>
    </section>
  );
}
