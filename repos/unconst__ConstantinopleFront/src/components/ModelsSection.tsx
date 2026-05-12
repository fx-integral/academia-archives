import { motion } from 'framer-motion';
import { useEffect, useState } from 'react';

interface ModelData {
  name: string;
  provider: string;
  latency: number;
  inputPrice: number;
  outputPrice: number;
  context: string;
  uptime: number;
  capabilities: string[];
}

const models: ModelData[] = [
  { name: 'claude-3.7-sonnet', provider: 'Anthropic', latency: 280, inputPrice: 3.0, outputPrice: 15.0, context: '200K', uptime: 99.98, capabilities: ['tool_use', 'vision', 'stream'] },
  { name: 'gpt-4o', provider: 'OpenAI', latency: 320, inputPrice: 2.5, outputPrice: 10.0, context: '128K', uptime: 99.95, capabilities: ['tool_use', 'vision', 'stream'] },
  { name: 'llama-3.3-70b', provider: 'Meta', latency: 180, inputPrice: 0.8, outputPrice: 0.8, context: '131K', uptime: 99.99, capabilities: ['tool_use', 'stream'] },
  { name: 'qwen-2.5-72b', provider: 'Alibaba', latency: 120, inputPrice: 0.9, outputPrice: 0.9, context: '131K', uptime: 99.97, capabilities: ['tool_use', 'stream'] },
  { name: 'deepseek-r1', provider: 'DeepSeek', latency: 450, inputPrice: 1.4, outputPrice: 5.6, context: '65K', uptime: 99.92, capabilities: ['reasoning', 'stream'] },
  { name: 'gemini-2.5-pro', provider: 'Google', latency: 350, inputPrice: 1.25, outputPrice: 5.0, context: '1M', uptime: 99.96, capabilities: ['tool_use', 'vision', 'stream'] },
];

function useJitter(base: number, range: number) {
  const [value, setValue] = useState(base);
  useEffect(() => {
    const interval = setInterval(() => {
      setValue(base + Math.round((Math.random() - 0.5) * range));
    }, 2000 + Math.random() * 1000);
    return () => clearInterval(interval);
  }, [base, range]);
  return value;
}

function ModelRow({ model, index }: { model: ModelData; index: number }) {
  const latency = useJitter(model.latency, 40);

  return (
    <motion.tr
      initial={{ opacity: 0, y: 10 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true }}
      transition={{ duration: 0.4, delay: index * 0.06 }}
      className="border-b border-white/[0.06] last:border-b-0 group"
    >
      <td className="py-5 pr-6">
        <div className="font-sans text-sm text-g3-text">{model.name}</div>
        <div className="font-sans text-xs text-g3-text-muted mt-0.5">{model.provider}</div>
      </td>
      <td className="py-5 pr-6">
        <div className="flex items-center gap-2">
          <div className="w-1.5 h-1.5 rounded-full bg-emerald-400/80" />
          <span className="font-sans text-sm text-g3-text-secondary tabular-nums">{latency}ms</span>
        </div>
      </td>
      <td className="py-5 pr-6">
        <span className="font-sans text-sm text-g3-text-secondary">${model.inputPrice.toFixed(2)}</span>
        <span className="font-sans text-xs text-g3-text-muted"> / </span>
        <span className="font-sans text-sm text-g3-text-secondary">${model.outputPrice.toFixed(2)}</span>
      </td>
      <td className="py-5 pr-6 hidden md:table-cell">
        <span className="font-sans text-sm text-g3-text-muted">{model.context}</span>
      </td>
      <td className="py-5 hidden lg:table-cell">
        <div className="flex gap-2">
          {model.capabilities.map((cap) => (
            <span key={cap} className="font-sans text-[11px] text-g3-text-muted border border-white/[0.08] rounded-full px-2.5 py-0.5">
              {cap}
            </span>
          ))}
        </div>
      </td>
    </motion.tr>
  );
}

export function ModelsSection() {
  return (
    <section id="models" className="relative py-32 px-8 lg:px-16">
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
              Live metrics
            </span>
          </div>
          <h2 className="font-serif text-4xl sm:text-5xl text-g3-text leading-tight tracking-[-0.02em]">
            Models available
          </h2>
        </motion.div>

        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-white/[0.1]">
                <th className="text-left pb-4 font-sans text-xs text-g3-text-muted tracking-widest uppercase">Model</th>
                <th className="text-left pb-4 font-sans text-xs text-g3-text-muted tracking-widest uppercase">Latency</th>
                <th className="text-left pb-4 font-sans text-xs text-g3-text-muted tracking-widest uppercase">Price / M tok</th>
                <th className="text-left pb-4 font-sans text-xs text-g3-text-muted tracking-widest uppercase hidden md:table-cell">Context</th>
                <th className="text-left pb-4 font-sans text-xs text-g3-text-muted tracking-widest uppercase hidden lg:table-cell">Capabilities</th>
              </tr>
            </thead>
            <tbody>
              {models.map((model, i) => (
                <ModelRow key={model.name} model={model} index={i} />
              ))}
            </tbody>
          </table>
        </div>

        <motion.p
          initial={{ opacity: 0 }}
          whileInView={{ opacity: 1 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5, delay: 0.3 }}
          className="mt-8 font-sans text-sm text-g3-text-muted"
        >
          Machine-readable at{' '}
          <span className="text-g3-text-secondary">/.well-known/inference.json</span>
          {' '}and{' '}
          <span className="text-g3-text-secondary">/pricing.json</span>
        </motion.p>
      </div>
    </section>
  );
}
