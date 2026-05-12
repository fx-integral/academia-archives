import { motion } from 'framer-motion';

export function DocsPage() {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.4 }}
      className="relative z-20 min-h-screen pt-28 pb-20 px-8 lg:px-16"
    >
      <div className="max-w-3xl mx-auto">
        <div className="mb-12">
          <div className="flex items-center gap-4 mb-6">
            <div className="w-5 h-px bg-g3-text-secondary" />
            <span className="font-sans text-xs text-g3-text-secondary tracking-widest uppercase">
              Documentation
            </span>
          </div>
          <h2 className="font-serif text-4xl sm:text-5xl text-g3-text leading-tight tracking-[-0.02em]">
            Constantinople
          </h2>
        </div>

        <div className="space-y-8 font-sans text-base text-g3-text-secondary leading-[1.85]">
          <p>
            The true opposite of a closed AI company is one where every query is made available to the public.
            Sure, there will always be demand for private intelligence, but as social networks taught us, there is also demand to be seen, and value to that which is shared. 
            We are building that network: a network of intelligence where inference is cheaper, faster, and more accessible than ever before. One where that intelligence is collectively owned and shared.
            To do it, we build a network where any computer in the world can compete to run your inference, where the best are rewarded with more resources, and where the entire process is transparent and verifiable.
          </p>

          <p>
            Every query that flows through Constantinople is sanitized — personally identifiable information
            is stripped — and then published to a public dataset. This is the core principle: intelligence
            generated through decentralized compute belongs to everyone. The dataset grows with every request,
            creating a shared commons of inference artifacts.
          </p>

          <p>
            We use a Bittensor mining network to run Constantinople where miners (compute providers) are paid based on the time to first token (TTFT), accuracy of hidden state verification,
            and consistency over time. This openness means that truly Constantinople is the opposite of a closed AI company, you can't game the system, you can't exploit the system, you can't hide the system.
          </p>
        </div>
      </div>
    </motion.div>
  );
}
