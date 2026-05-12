import { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Navbar } from './components/Navbar';
import { HeroContent } from './components/HeroContent';
import { DatasetPage } from './components/DatasetPage';
import { DocsPage } from './components/DocsPage';
import { StatusPage } from './components/StatusPage';
import { APIPage } from './components/APIPage';
import { MinerDocsPage } from './components/MinerDocsPage';

import { VideoBackground } from './components/VideoBackground';

export type Page = 'home' | 'dataset' | 'docs' | 'status' | 'api' | 'miners';

const validPages: Page[] = ['home', 'dataset', 'docs', 'status', 'api', 'miners'];

function getPageFromHash(): Page {
  const hash = window.location.hash.slice(1);
  if (hash && validPages.includes(hash as Page)) return hash as Page;
  return 'home';
}

function App() {
  const [page, setPage] = useState<Page>(getPageFromHash);

  const navigate = useCallback((p: Page) => {
    setPage(p);
    window.location.hash = p === 'home' ? '' : p;
  }, []);

  useEffect(() => {
    const onHashChange = () => setPage(getPageFromHash());
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  return (
    <main className="min-h-screen bg-g3-bg relative">
      <VideoBackground />

      <Navbar activePage={page} onNavigate={navigate} />

      <div className="relative z-10">
        <AnimatePresence mode="wait">
          {page === 'home' && (
            <motion.div
              key="home"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.35 }}
            >
              <HeroContent />
            </motion.div>
          )}
          {page === 'dataset' && (
            <motion.div
              key="dataset"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.35 }}
            >
              <DatasetPage />
            </motion.div>
          )}
          {page === 'docs' && (
            <motion.div
              key="docs"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.35 }}
            >
              <DocsPage />
            </motion.div>
          )}
          {page === 'status' && (
            <motion.div
              key="status"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.35 }}
            >
              <StatusPage />
            </motion.div>
          )}
          {page === 'api' && (
            <motion.div
              key="api"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.35 }}
            >
              <APIPage />
            </motion.div>
          )}
          {page === 'miners' && (
            <motion.div
              key="miners"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.35 }}
            >
              <MinerDocsPage />
            </motion.div>
          )}
        </AnimatePresence>
      </div>

    </main>
  );
}

export default App;
