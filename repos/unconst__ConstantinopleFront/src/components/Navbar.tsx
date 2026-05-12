import { motion } from 'framer-motion';
import type { Page } from '../App';
import { TickerBar } from './TickerBar';

interface NavbarProps {
  activePage: Page;
  onNavigate: (page: Page) => void;
}

export function Navbar({ activePage, onNavigate }: NavbarProps) {
  const navItems: { page: Page; label: string }[] = [
    { page: 'status', label: 'Status' },
    { page: 'api', label: 'API' },
    { page: 'docs', label: 'Docs' },
    { page: 'miners', label: 'Miners' },
  ];

  return (
    <motion.header
      initial={{ opacity: 0, y: -20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.6, delay: 0.2, ease: [0.4, 0, 0.2, 1] }}
      className="fixed top-0 left-0 right-0 z-50 h-20"
    >
      <div className="h-full px-8 lg:px-16 flex items-center justify-between relative">
        <button
          onClick={() => onNavigate('home')}
          className="flex items-center gap-2 cursor-pointer z-10"
        >
          <span className="font-serif text-lg font-bold text-g3-text tracking-tight">Constantinople</span>
        </button>

        <div className="hidden lg:block absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2">
          <TickerBar />
        </div>

        <nav className="flex items-center gap-6 z-10">
          {navItems.map(({ page, label }) => (
            <button
              key={page}
              onClick={() => onNavigate(page)}
              className={`text-sm font-medium transition-colors ${
                activePage === page
                  ? 'text-g3-accent'
                  : 'text-g3-muted hover:text-g3-text'
              }`}
            >
              {label}
            </button>
          ))}
        </nav>

      </div>

      {/* Mobile ticker - scrollable row below header */}
      <div className="lg:hidden px-4 pb-2 overflow-x-auto scrollbar-none">
        <TickerBar />
      </div>
    </motion.header>
  );
}
