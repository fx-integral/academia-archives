import { useEffect, useRef, useState } from 'react';

const CLIP_COUNT = 6;
const ROTATE_MS = 30_000;

function randomClip(exclude: number): number {
  let n;
  do { n = Math.floor(Math.random() * CLIP_COUNT) + 1; }
  while (n === exclude);
  return n;
}

export function VideoBackground() {
  const videoA = useRef<HTMLVideoElement>(null);
  const videoB = useRef<HTMLVideoElement>(null);
  const [isMobile, setIsMobile] = useState(false);
  const [front, setFront] = useState<'a' | 'b'>('a');
  const [ready, setReady] = useState(false);
  const [initialClip] = useState(() => randomClip(0));
  const clips = useRef({ a: 0, b: 0 });

  useEffect(() => {
    const mobile = window.matchMedia('(max-width: 768px)').matches;
    setIsMobile(mobile);
    if (mobile) return;

    const canWebm = document.createElement('video').canPlayType('video/webm; codecs="vp9"') !== '';
    const ext = canWebm ? 'webm' : 'mp4';

    const clipA = initialClip;
    const clipB = randomClip(clipA);
    clips.current = { a: clipA, b: clipB };

    const vA = videoA.current!;
    const vB = videoB.current!;

    vA.src = `/clouds-${clipA}.${ext}`;
    vA.poster = `/clouds-${clipA}-poster.jpg`;
    vB.src = `/clouds-${clipB}.${ext}`;
    vB.poster = `/clouds-${clipB}-poster.jpg`;
    vA.load();
    vB.load();

    vA.addEventListener('canplay', () => setReady(true), { once: true });

    const tryPlay = (v: HTMLVideoElement) => {
      v.play().catch(() => {
        const resume = () => { v.play().catch(() => {}); document.removeEventListener('click', resume); };
        document.addEventListener('click', resume, { once: true });
      });
    };

    setTimeout(() => { tryPlay(vA); tryPlay(vB); }, 100);

    let currentFront: 'a' | 'b' = 'a';
    const timer = setInterval(() => {
      const newFront: 'a' | 'b' = currentFront === 'a' ? 'b' : 'a';
      currentFront = newFront;
      setFront(newFront);

      setTimeout(() => {
        const backKey: 'a' | 'b' = newFront === 'a' ? 'b' : 'a';
        const backVideo = backKey === 'a' ? vA : vB;
        const newClip = randomClip(clips.current[newFront]);
        clips.current[backKey] = newClip;

        backVideo.src = `/clouds-${newClip}.${ext}`;
        backVideo.poster = `/clouds-${newClip}-poster.jpg`;
        backVideo.load();
        backVideo.play().catch(() => {});
      }, 2500);
    }, ROTATE_MS);

    return () => clearInterval(timer);
  }, [initialClip, isMobile]);

  if (isMobile) {
    return (
      <div className="fixed inset-0 z-0 overflow-hidden bg-g3-bg">
        <img src={`/clouds-${initialClip}-poster.jpg`} alt="" className="hero-poster" />
        <div className="absolute inset-0 bg-[#0a1520]/20 mix-blend-multiply" />
        <div className="absolute inset-0 bg-gradient-to-b from-black/20 via-black/10 to-black/35" />
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-0 overflow-hidden bg-g3-bg">
      <video
        ref={videoA}
        autoPlay
        muted
        loop
        playsInline
        preload="auto"
        className={`hero-video${ready ? ' loaded' : ''}${front !== 'a' ? ' hero-video-out' : ''}`}
      />
      <video
        ref={videoB}
        autoPlay
        muted
        loop
        playsInline
        preload="auto"
        className={`hero-video${ready ? ' loaded' : ''}${front !== 'b' ? ' hero-video-out' : ''}`}
      />

      <div className="absolute inset-0 bg-[#0a1520]/20 mix-blend-multiply" />
      <div className="absolute inset-0 bg-gradient-to-b from-black/20 via-black/10 to-black/35" />
    </div>
  );
}
