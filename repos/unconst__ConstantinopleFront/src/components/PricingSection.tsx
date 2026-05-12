import { motion } from 'framer-motion';

const pricingData = [
  { model: 'claude-3.7-sonnet', input: '$3.00', output: '$15.00', context: '200K' },
  { model: 'gpt-4o', input: '$2.50', output: '$10.00', context: '128K' },
  { model: 'llama-3.3-70b', input: '$0.80', output: '$0.80', context: '131K' },
  { model: 'qwen-2.5-72b', input: '$0.90', output: '$0.90', context: '131K' },
  { model: 'deepseek-r1', input: '$1.40', output: '$5.60', context: '65K' },
  { model: 'gemini-2.5-pro', input: '$1.25', output: '$5.00', context: '1M' },
];

export function PricingSection() {
  return (
    <section id="pricing" className="relative py-32 px-8 lg:px-16">
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
              Transparent pricing
            </span>
          </div>
          <h2 className="font-serif text-4xl sm:text-5xl text-g3-text leading-tight tracking-[-0.02em]">
            Pay per token.
          </h2>
          <p className="font-sans text-base text-g3-text-secondary mt-4 max-w-lg leading-relaxed">
            No subscriptions. No minimums. Machine-readable at{' '}
            <span className="text-g3-text-secondary font-mono text-sm">/pricing.json</span>
          </p>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5, delay: 0.1 }}
          className="overflow-x-auto"
        >
          <table className="w-full">
            <thead>
              <tr className="border-b border-white/[0.1]">
                <th className="text-left pb-4 font-sans text-xs text-g3-text-muted tracking-widest uppercase">Model</th>
                <th className="text-left pb-4 font-sans text-xs text-g3-text-muted tracking-widest uppercase">Input / M tokens</th>
                <th className="text-left pb-4 font-sans text-xs text-g3-text-muted tracking-widest uppercase">Output / M tokens</th>
                <th className="text-left pb-4 font-sans text-xs text-g3-text-muted tracking-widest uppercase">Context</th>
              </tr>
            </thead>
            <tbody>
              {pricingData.map((row) => (
                <tr key={row.model} className="border-b border-white/[0.05] last:border-b-0">
                  <td className="py-4 font-sans text-sm text-g3-text">{row.model}</td>
                  <td className="py-4 font-sans text-sm text-g3-text-secondary">{row.input}</td>
                  <td className="py-4 font-sans text-sm text-g3-text-secondary">{row.output}</td>
                  <td className="py-4 font-sans text-sm text-g3-text-muted">{row.context}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5, delay: 0.2 }}
          className="mt-16 grid grid-cols-1 md:grid-cols-2 gap-12"
        >
          <div>
            <h3 className="font-sans text-base font-medium text-g3-text mb-2 tracking-wide">Free tier</h3>
            <p className="font-sans text-sm text-g3-text-secondary leading-relaxed">
              1M tokens per month. 10 requests per minute. No credit card.
            </p>
          </div>
          <div>
            <h3 className="font-sans text-base font-medium text-g3-text mb-2 tracking-wide">Enterprise</h3>
            <p className="font-sans text-sm text-g3-text-secondary leading-relaxed">
              Dedicated capacity, custom SLA, priority routing, volume discounts.
            </p>
          </div>
        </motion.div>
      </div>
    </section>
  );
}
