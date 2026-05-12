import { motion } from 'framer-motion';

const features = [
  { title: 'Streaming', description: 'Server-sent events for real-time token delivery. First token in under 100ms.' },
  { title: 'Tool calling', description: 'Native function calling across all supported models. OpenAI-compatible schema.' },
  { title: 'Batch inference', description: 'Submit thousands of requests. Get results via webhook or polling.' },
  { title: 'Smart routing', description: 'Auto-route to the fastest or cheapest provider. Automatic fallback on failure.' },
  { title: 'Async webhooks', description: 'Fire and forget. Results are POSTed to your callback URL when ready.' },
  { title: 'Usage telemetry', description: 'Real-time token counts, cost tracking, and rate limit visibility via API.' },
];

export function FeaturesSection() {
  return (
    <section id="docs" className="relative py-32 px-8 lg:px-16">
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
              Capabilities
            </span>
          </div>
          <h2 className="font-serif text-4xl sm:text-5xl text-g3-text leading-tight tracking-[-0.02em]">
            Built for machines.
          </h2>
        </motion.div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-x-12 gap-y-14">
          {features.map((feature, i) => (
            <motion.div
              key={feature.title}
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.5, delay: i * 0.07 }}
            >
              <h3 className="font-sans text-base font-medium text-g3-text mb-3 tracking-wide">
                {feature.title}
              </h3>
              <p className="font-sans text-sm text-g3-text-secondary leading-relaxed">
                {feature.description}
              </p>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}
