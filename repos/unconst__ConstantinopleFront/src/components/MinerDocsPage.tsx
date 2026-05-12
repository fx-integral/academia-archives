import { motion } from 'framer-motion';

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-12">
      <h3 className="font-serif text-2xl sm:text-3xl text-g3-text mb-6 tracking-[-0.01em]">
        {title}
      </h3>
      <div className="space-y-4 font-sans text-base text-g3-text-secondary leading-[1.85]">
        {children}
      </div>
    </div>
  );
}

function CodeBlock({ children }: { children: string }) {
  return (
    <pre className="bg-white/[0.03] border border-white/[0.08] rounded-lg p-4 overflow-x-auto font-mono text-sm text-g3-text-secondary leading-relaxed">
      <code>{children}</code>
    </pre>
  );
}

function InfoCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-white/[0.02] border border-white/[0.08] rounded-lg p-5">
      <h4 className="font-sans text-sm font-medium text-g3-text mb-2 tracking-wide">{title}</h4>
      <div className="font-sans text-sm text-g3-text-secondary leading-relaxed">{children}</div>
    </div>
  );
}

export function MinerDocsPage() {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.4 }}
      className="relative z-20 min-h-screen pt-28 pb-20 px-8 lg:px-16"
    >
      <div className="max-w-3xl mx-auto">
        {/* Header */}
        <div className="mb-12">
          <div className="flex items-center gap-4 mb-6">
            <div className="w-5 h-px bg-g3-text-secondary" />
            <span className="font-sans text-xs text-g3-text-secondary tracking-widest uppercase">
              For Miners
            </span>
          </div>
          <h2 className="font-serif text-4xl sm:text-5xl text-g3-text leading-tight tracking-[-0.02em]">
            Mining on Constantinople
          </h2>
          <p className="mt-4 font-sans text-lg text-g3-text-secondary leading-relaxed">
            Everything you need to start mining on SN97 -- hardware requirements, setup instructions,
            and how the verification and incentive system works.
          </p>
        </div>

        {/* How Verification Works */}
        <Section title="How verification works">
          <p>
            Constantinople uses an inline hidden state commitment protocol to verify that miners
            are running genuine inference. When a request comes in, the validator tells the miner
            to commit the hidden state at a randomly selected layer and position. The miner returns
            this commitment alongside the inference response.
          </p>
          <p>
            The validator then independently computes the reference hidden state using its own copy
            of the model and compares it against the miner's commitment via cosine similarity.
            Honest miners running the correct model will produce near-identical hidden states
            (cosine ~1.0). This verification happens offline -- it adds zero latency to the
            inference response.
          </p>
          <p>
            Each commitment is also bound to a per-request, per-miner nonce via cryptographic hash.
            This prevents relay attacks where a miner forwards requests to someone else's hardware.
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
            <InfoCard title="What's checked">
              <ul className="list-disc list-inside space-y-1">
                <li>Hidden state correctness (cosine similarity)</li>
                <li>Nonce binding (anti-relay proof)</li>
                <li>Response latency and throughput</li>
                <li>Commitment participation rate</li>
              </ul>
            </InfoCard>
            <InfoCard title="Selection is random">
              <ul className="list-disc list-inside space-y-1">
                <li>Layer: randomly chosen each request</li>
                <li>Position: random offset in the sequence</li>
                <li>Miners cannot predict what will be checked</li>
                <li>All requests are eligible for verification</li>
              </ul>
            </InfoCard>
          </div>
        </Section>

        {/* How Incentives Work */}
        <Section title="How miners earn emissions">
          <p>
            Constantinople runs on Bittensor's incentive mechanism. The validator sets weights
            on-chain for each miner based on their performance. At each tempo boundary, Bittensor's
            Yuma Consensus distributes emissions proportional to these weights.
          </p>
          <p>
            Your weight is determined by three factors:
          </p>
          <div className="grid grid-cols-1 gap-4 mt-2">
            <InfoCard title="Speed (40%)">
              Tokens per second and time to first token. Faster miners earn more. We measure
              wall-clock speed from the gateway -- self-reported metrics are capped to prevent
              inflation. Invest in hardware optimization, efficient batching, and low-latency
              networking.
            </InfoCard>
            <InfoCard title="Verification (40%)">
              Hidden state commitment pass rate and cosine similarity. Miners running the correct
              model honestly will consistently pass at cosine ~1.0. Failed or missing commitments
              reduce your verification score.
            </InfoCard>
            <InfoCard title="Consistency (20%)">
              Uptime and reliability over time. Miners that maintain steady performance with low
              variance get rewarded. Intermittent availability, frequent errors, and dropped
              requests hurt this score.
            </InfoCard>
          </div>
          <p className="mt-4">
            The optimal strategy is straightforward: run the correct model on good hardware,
            keep your miner online, and optimize for throughput. There are no shortcuts --
            the verification system is designed so that honest, fast inference is the highest-paying
            approach.
          </p>
        </Section>

        {/* Getting Started */}
        <Section title="Getting started">
          <p>
            Mining on SN97 requires a GPU capable of running Qwen2.5-7B-Instruct with reasonable
            throughput, plus registration on the Bittensor network.
          </p>

          <h4 className="font-sans text-lg text-g3-text mt-6 mb-3">Hardware requirements</h4>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <InfoCard title="Minimum">
              <ul className="list-disc list-inside space-y-1">
                <li>1x RTX 4090 (24GB VRAM)</li>
                <li>32GB system RAM</li>
                <li>Stable internet connection</li>
                <li>Low-latency network path to validator</li>
              </ul>
            </InfoCard>
            <InfoCard title="Recommended">
              <ul className="list-disc list-inside space-y-1">
                <li>1-2x RTX 5090 or A100 (high throughput)</li>
                <li>64GB+ system RAM</li>
                <li>Dedicated server with static IP</li>
                <li>SSD for model weight storage</li>
              </ul>
            </InfoCard>
          </div>

          <h4 className="font-sans text-lg text-g3-text mt-8 mb-3">Step 1: Register on SN97</h4>
          <p>
            You'll need a Bittensor wallet with enough TAO to register a miner UID on subnet 97.
            Registration costs vary with demand.
          </p>
          <CodeBlock>{`# Install bittensor
pip install bittensor

# Create or import wallet
btcli wallet create --wallet.name miner_wallet

# Register on SN97
btcli subnet register --netuid 97 --wallet.name miner_wallet`}</CodeBlock>

          <h4 className="font-sans text-lg text-g3-text mt-8 mb-3">Step 2: Install dependencies</h4>
          <CodeBlock>{`pip install vllm fastapi uvicorn aiohttp numpy pydantic accelerate`}</CodeBlock>

          <h4 className="font-sans text-lg text-g3-text mt-8 mb-3">Step 3: Run the miner</h4>
          <p>
            The miner runs vLLM for high-throughput inference and a HuggingFace model for hidden
            state extraction. Both are needed for the verification protocol.
          </p>
          <CodeBlock>{`python vllm_miner.py \\
  --model Qwen/Qwen2.5-7B-Instruct \\
  --port 8091 \\
  --hf-device cpu \\
  --gpu-memory-utilization 0.85`}</CodeBlock>
          <p className="mt-2">
            The <code className="font-mono text-sm bg-white/[0.05] px-1.5 py-0.5 rounded">--hf-device cpu</code> flag
            runs the hidden state model on CPU, leaving GPU memory for vLLM's KV cache. For multi-GPU
            setups, add <code className="font-mono text-sm bg-white/[0.05] px-1.5 py-0.5 rounded">--tensor-parallel-size 2</code>.
          </p>

          <h4 className="font-sans text-lg text-g3-text mt-8 mb-3">Step 4: Serve your axon</h4>
          <p>
            Your miner must be reachable at the IP and port registered on-chain. Ensure your
            firewall allows inbound connections on the miner port, and that the axon endpoint
            is correctly registered in the metagraph.
          </p>
        </Section>

        {/* What NOT to do */}
        <Section title="What gets penalized">
          <p>
            The verification system is designed to make cheating unprofitable.  These behaviors
            are detected and penalized:
          </p>
          <div className="space-y-3 mt-4">
            <div className="flex gap-3 items-start">
              <span className="text-red-400 mt-0.5 flex-shrink-0">&#x2717;</span>
              <div>
                <span className="text-g3-text font-medium">Fake hidden states</span>
                <span className="text-g3-text-secondary"> -- Returning fabricated or cached hidden states from a different model will produce low cosine similarity and trigger immediate score penalties.</span>
              </div>
            </div>
            <div className="flex gap-3 items-start">
              <span className="text-red-400 mt-0.5 flex-shrink-0">&#x2717;</span>
              <div>
                <span className="text-g3-text font-medium">Relay/proxy attacks</span>
                <span className="text-g3-text-secondary"> -- Forwarding requests to an external API or another miner's hardware is caught by nonce verification. The cryptographic binding ensures only the intended miner can produce valid commitments.</span>
              </div>
            </div>
            <div className="flex gap-3 items-start">
              <span className="text-red-400 mt-0.5 flex-shrink-0">&#x2717;</span>
              <div>
                <span className="text-g3-text font-medium">Commitment evasion</span>
                <span className="text-g3-text-secondary"> -- Dropping or ignoring commitment requests is tracked. Miners with high miss rates receive progressive weight penalties that compound with other scores.</span>
              </div>
            </div>
            <div className="flex gap-3 items-start">
              <span className="text-red-400 mt-0.5 flex-shrink-0">&#x2717;</span>
              <div>
                <span className="text-g3-text font-medium">TPS inflation</span>
                <span className="text-g3-text-secondary"> -- Self-reported metrics are validated against wall-clock measurements at the gateway. Inflated numbers are automatically clamped.</span>
              </div>
            </div>
            <div className="flex gap-3 items-start">
              <span className="text-red-400 mt-0.5 flex-shrink-0">&#x2717;</span>
              <div>
                <span className="text-g3-text font-medium">Intermittent availability</span>
                <span className="text-g3-text-secondary"> -- Miners that go offline frequently or have high error rates lose consistency score and receive less weight over time.</span>
              </div>
            </div>
          </div>
          <p className="mt-6">
            The system uses layered, compounding penalties. No single evasion strategy avoids all
            detection. The economically optimal approach is always honest, fast inference.
          </p>
        </Section>

        {/* Model */}
        <Section title="Current model">
          <p>
            Constantinople currently runs <strong className="text-g3-text">Qwen/Qwen2.5-7B-Instruct</strong>.
            All miners must run this exact model -- the verification protocol compares hidden states
            against a reference copy, so different models or fine-tunes will fail verification.
          </p>
          <p>
            The model is fully open (no HuggingFace token needed) and requires approximately 14GB
            of VRAM for inference with vLLM.
          </p>
        </Section>

        {/* FAQ */}
        <Section title="Frequently asked questions">
          <div className="space-y-6">
            <div>
              <h4 className="font-sans text-base text-g3-text mb-1">Do I need funding from the team to start mining?</h4>
              <p>
                No. Miners self-fund their registration on subnet 97. You need TAO in your wallet to
                cover the registration cost -- this is standard Bittensor behavior. Once registered,
                you start earning emissions based on your performance. There is no application process
                or approval needed.
              </p>
            </div>
            <div>
              <h4 className="font-sans text-base text-g3-text mb-1">What are the expected earnings?</h4>
              <p>
                Earnings depend on your hardware performance, uptime, and the total number of miners
                competing for weight. Better hardware and consistent uptime translate directly to
                higher emissions. Check{' '}
                <a href="https://taostats.io/subnets/97" target="_blank" rel="noopener noreferrer" className="text-g3-accent hover:underline">
                  taostats.io/subnets/97
                </a>{' '}
                for current emission rates and miner standings.
              </p>
            </div>
            <div>
              <h4 className="font-sans text-base text-g3-text mb-1">Can I use a cloud GPU provider?</h4>
              <p>
                Yes. Many miners use cloud GPU providers like RunPod, Lambda, or Lium. Any provider
                that gives you a dedicated GPU with sufficient VRAM and a stable network connection
                will work. Make sure you have SSH access and can open a port for inbound connections.
              </p>
            </div>
            <div>
              <h4 className="font-sans text-base text-g3-text mb-1">Can I run a fine-tuned or quantized model?</h4>
              <p>
                No. The verification protocol compares hidden states against the reference model
                (Qwen2.5-7B-Instruct). Any modification to the model weights -- including fine-tuning,
                quantization, or distillation -- will produce different hidden states and fail
                verification. Run the exact model specified.
              </p>
            </div>
            <div>
              <h4 className="font-sans text-base text-g3-text mb-1">How do I update my axon endpoint?</h4>
              <p>
                Your miner automatically registers its axon endpoint on-chain when it starts. If your
                IP or port changes, restart the miner and it will update the metagraph. The validator
                discovers miners through the on-chain metagraph -- no manual configuration needed.
              </p>
            </div>
          </div>
        </Section>

        {/* Resources */}
        <div className="mt-16 pt-8 border-t border-white/[0.08]">
          <h3 className="font-serif text-xl text-g3-text mb-4">Resources</h3>
          <ul className="space-y-2 font-sans text-sm text-g3-text-secondary">
            <li>
              <a href="https://github.com/unconst/Constantinople" target="_blank" rel="noopener noreferrer" className="text-g3-accent hover:underline">
                GitHub Repository
              </a>
              <span className="ml-2">-- Source code and miner software</span>
            </li>
            <li>
              <a href="https://taostats.io/subnets/97" target="_blank" rel="noopener noreferrer" className="text-g3-accent hover:underline">
                Taostats SN97
              </a>
              <span className="ml-2">-- On-chain metrics and miner leaderboard</span>
            </li>
            <li>
              <a href="https://huggingface.co/Qwen/Qwen2.5-7B-Instruct" target="_blank" rel="noopener noreferrer" className="text-g3-accent hover:underline">
                Qwen2.5-7B-Instruct
              </a>
              <span className="ml-2">-- Model weights on HuggingFace</span>
            </li>
          </ul>
        </div>
      </div>
    </motion.div>
  );
}
