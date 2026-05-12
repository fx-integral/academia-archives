import { motion } from 'framer-motion';
import { useCopySkill } from '../hooks/use-copy-skill';

export function Footer({ onNavigate }: { onNavigate?: (page: 'home' | 'dataset' | 'docs' | 'status' | 'api') => void }) {
  const { copy, copied } = useCopySkill();

  return (
    <footer className="relative border-t border-white/[0.08] py-20 px-8 lg:px-16">
      <div className="max-w-7xl mx-auto">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5 }}
          className="grid grid-cols-1 md:grid-cols-3 gap-16"
        >
          <div>
            <div className="flex items-center gap-2 mb-4">
              <span className="font-serif text-lg font-bold text-g3-text tracking-tight">Constantinople</span>
              <span className="text-g3-text-muted">|</span>
              <span className="font-sans text-sm text-g3-text-secondary tracking-wide">SN97</span>
            </div>
            <p className="font-sans text-sm text-g3-text-muted leading-relaxed">
              Let intelligence belong to the world. Blazing fast, always-on, agentic inference — sanitized and shared publicly.
            </p>
          </div>

          <div>
            <h4 className="font-sans text-xs text-g3-text-muted tracking-widest uppercase mb-5">
              Links
            </h4>
            <div className="space-y-3">
              <button onClick={copy} className="block font-sans text-sm text-g3-text-secondary hover:text-g3-text transition-colors duration-300">
                {copied ? 'Copied!' : 'Copy SKILL.md'}
              </button>
              <button onClick={() => { if (onNavigate) onNavigate('api'); else window.location.hash = 'api'; }} className="block font-sans text-sm text-g3-text-secondary hover:text-g3-text transition-colors duration-300">API</button>
              <a href="/llm.txt" className="block font-mono text-[13px] text-g3-text-secondary hover:text-g3-text transition-colors duration-300">/llm.txt</a>
              <a href="/agents.txt" className="block font-mono text-[13px] text-g3-text-secondary hover:text-g3-text transition-colors duration-300">/agents.txt</a>
            </div>
          </div>

          <div>
            <h4 className="font-sans text-xs text-g3-text-muted tracking-widest uppercase mb-5">
              Network
            </h4>
            <div className="space-y-3">
              <span className="block font-sans text-sm text-g3-text-secondary">Bittensor Subnet 97</span>
              <span className="block font-sans text-sm text-g3-text-secondary">Model: Qwen2.5-7B-Instruct</span>
              <span className="block font-sans text-sm text-g3-text-muted">Hidden state verification</span>
            </div>
          </div>
        </motion.div>

        <div className="mt-16 pt-8 border-t border-white/[0.06] flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
          <span className="font-sans text-xs text-g3-text-muted tracking-wide">
            Constantinople — Decentralized inference
          </span>
          <button onClick={copy} className="font-mono text-xs text-g3-text-muted hover:text-g3-text transition-colors">
            {copied ? 'Copied!' : '/SKILL.md'}
          </button>
        </div>
      </div>
    </footer>
  );
}
