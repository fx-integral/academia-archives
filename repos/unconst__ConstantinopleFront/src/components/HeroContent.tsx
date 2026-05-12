import { motion } from 'framer-motion';
import { useState, useCallback } from 'react';

const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: {
      staggerChildren: 0.1,
      delayChildren: 0.5,
    },
  },
};

const wordVariants = {
  hidden: { opacity: 0, y: 30 },
  visible: {
    opacity: 1,
    y: 0,
    transition: {
      duration: 0.6,
      ease: [0.4, 0, 0.2, 1] as const,
    },
  },
};

export function HeroContent() {
  const headlineWords = ['Intelligence', 'belongs', 'free.'];
  const curlCommand = 'curl -fsSL https://constantinople.cloud/skill.txt';
  const [copied, setCopied] = useState(false);

  const copyCommand = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(curlCommand);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // fallback: select the text
    }
  }, [curlCommand]);

  return (
    <div className="min-h-screen flex flex-col justify-center items-center px-8 lg:px-16 pt-20 text-center">
      <div className="max-w-4xl mx-auto w-full space-y-10">
        <motion.h1
          variants={containerVariants}
          initial="hidden"
          animate="visible"
          className="font-serif text-5xl sm:text-6xl lg:text-7xl xl:text-[80px] text-g3-text leading-[1.05] tracking-[-0.02em]"
        >
          {headlineWords.map((word, index) => (
            <motion.span
              key={index}
              variants={wordVariants}
              className="inline-block mr-[0.25em]"
            >
              {word}
            </motion.span>
          ))}
        </motion.h1>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 1.0 }}
          className="w-full max-w-xl mx-auto"
        >
          <button
            onClick={copyCommand}
            className="group w-full bg-white/5 border border-white/15 rounded-lg px-5 py-3 hover:bg-white/10 hover:border-white/30 transition-all duration-250 cursor-pointer"
          >
            <code className="font-mono text-xs sm:text-sm text-g3-text/70">
              {curlCommand}
            </code>
            <span className="inline-block ml-3 text-xs opacity-40 group-hover:opacity-80 transition-opacity grayscale">
              {copied ? '✓' : '⎘'}
            </span>
          </button>
        </motion.div>
      </div>
    </div>
  );
}
